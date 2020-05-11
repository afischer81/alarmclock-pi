#!/usr/bin/env python3

import calendar
import copy
import datetime
import enum
import logging
import multiprocessing 
import os
import re
import signal
import subprocess
import sys

import pygame
from pygame.locals import *
import psutil

import requests

class ClockState(enum.Enum):
    RUN = 1
    ALARM = 2
    EDIT = 3

class AlarmClock:
    """
    Alarmclock for Raspberry Pi 7" touch screen display
    """

    def __init__(self, size=(800,480), logger=None) :
        if logger:
            self.log = logger
        else:
            self.log = logging.getLogger(__name__)

        self.rotated_display = True
        self.default_color = (255, 255, 255)
        self.night_color = (48, 48, 48)
        self.alarm_color = (192, 0, 0)
        self.bg_color = (0, 0, 0)
        self.ui_event = {}
        self.state = ClockState.RUN
        self.alarm_days = { "Mo" : True, "Di" : True, "Mi": True, "Do" : True, "Fr" : True, "Sa" : False, "So" : False }
        self.current_alarm = "7:00"
        self.radio_streams = []
        self.alarm_volume = [ 25, 70 ]
        self.play_start = None
        self.alarm_length = 120 # seconds
        self.play_process = None
        self.get_volume_cmd = 'amixer get \'PCM,0\''
        self.set_volume_cmd = 'amixer set \'PCM,0\' {0}%'

        with open('radio_streams.json', 'r') as f:
            self.radio_streams = json.load(f)
        self.log.info('read {0} radio URLs'.format(len(self.radio_streams)))
        self.current_radio = sorted(self.radio_streams.keys())[0]

        from evdev import InputDevice, list_devices
        devices = map(InputDevice, list_devices())
        eventX = ''
        for dev in devices:
            self.log.info('input device {0}'.format(dev.name))
            if dev.name == "ADS7846 Touchscreen":
                eventX = dev.path

        os.environ['SDL_FBDEV'] = '/dev/fb1'
        self.log.info('SDL_FBDEV = {0}'.format(os.environ['SDL_FBDEV']))
        os.environ['SDL_MOUSEDRV'] = 'TSLIB'
        self.log.info('SDL_MOUSEDRV = {0}'.format(os.environ['SDL_MOUSEDRV']))
        os.environ['SDL_MOUSEDEV'] = eventX
        self.log.info('SDL_MOUSEDEV = {0}'.format(os.environ['SDL_MOUSEDEV']))

        pygame.init()
        
        self.log.info('Window size: %d x %d' % (size[0], size[1]))
        self.screen = pygame.display.set_mode(size)

        # Clear the screen to start
        self.screen.fill(self.bg_color)
        # Initialise font support
        pygame.font.init()
        # Render the screen
        pygame.display.update()

        pygame.mouse.set_visible(False)
        self.w, self.h = self.screen.get_size()
        self.log.info('Screen size: %d x %d' % (self.w, self.h))
        self.clock = pygame.time.Clock()

        self.text_font = pygame.font.Font('/usr/share/fonts/truetype/freefont/FreeSansBold.ttf', round(self.h * 0.08))
        self.time_font = pygame.font.Font('font/gluqlo.ttf', round(self.h * 0.64))

        self.icons = []
        self.icons.append({ 'bright-' : pygame.image.load('icons/brightness_down.png') })
        self.icons.append({ 'bright+' : pygame.image.load('icons/brightness_up.png') })
        self.icons.append({ 'vol-' : pygame.image.load('icons/volume_down.png') })
        self.icons.append({ 'vol+' : pygame.image.load('icons/volume_up.png') })
        self.icons.append({ 'mute' : pygame.image.load('icons/volume_mute.png') })
        self.icons.append({ 'play' : pygame.image.load('icons/play_pause.png') })

        self.set_brightness(150)
    
    def set_brightness(self, value):
        self.log.info('set_brightness({0})'.format(value))
        current_brightness = self.get_brightness()
        if value == current_brightness:
            return
        with open('/sys/class/backlight/rpi_backlight/brightness', 'w') as f:
            f.write('{0}'.format(value))
    
    def get_brightness(self):
        value = 0
        with open('/sys/class/backlight/rpi_backlight/actual_brightness') as f:
            value = int(f.read())
        self.log.info('get_brightness() {0}'.format(value))
        return value

    def set_volume(self, value):
        self.log.info('set_volume({0})'.format(value))
        current_volume = self.get_volume()
        if value == current_volume:
            return
        os.system(self.set_volume_cmd.format(value))

    def get_volume(self):
        value = 0
        with subprocess.Popen(self.get_volume_cmd, shell=True, stdout=subprocess.PIPE).stdout as f:
            for line in f.readlines():
                m = re.search('(\d+)%', line.decode('utf-8'))
                if m:
                    value = int(m.group(1))
        return value

    def render_time(self, time, color):
        """
        Draw the current time in the center part.
        """
        self.log.info('render time {0}'.format(time))
        c = (self.default_color[0] * 0.04, self.default_color[1] * 0.04, self.default_color[2] * 0.04)
        self.screen.fill(c, (0.075 * self.w, 0.18 * self.h, 0.85 * self.w, 0.64 * self.h))
        [ hh, mm ] = time.split(':')
        s = self.time_font.size(hh)
        x = round((0.075 + 0.2) * self.w - s[0] / 2)
        y = round(0.5 * self.h - s[1] / 2)
        self.ui_event["hour+"] = pygame.Rect(x, y, s[0], s[1] / 2)
        self.ui_event["hour-"] = pygame.Rect(x, y + s[1] / 2, s[0], s[1] / 2)
        self.log.debug('hh p={0},{1},{2}'.format(x, y, s))
        surface = self.time_font.render(hh, True, color)
        self.screen.blit(surface, (x, y))
        s = self.time_font.size(mm)
        x = round((0.925 - 0.2) * self.w - s[0] / 2)
        y = round(0.5 * self.h - s[1] / 2)
        self.ui_event["min+"] = pygame.Rect(x, y, s[0], s[1] / 2)
        self.ui_event["min-"] = pygame.Rect(x, y + s[1] / 2, s[0], s[1] / 2)
        self.log.debug('mm p={0},{1},{2}'.format(x, y, s))
        surface = self.time_font.render(mm, True, color)
        self.screen.blit(surface, (x, y))
        self.screen.fill(self.bg_color, rect=(0.075 * self.w, 0.495 * self.h, 0.85 * self.w, 0.01 * self.h))
        self.screen.fill(self.bg_color, rect=(0.49 * self.w, 0.18 * self.h, 0.02 * self.w, 0.64 * self.h))

    def render_date(self, date, color):
        """
        Draw the date in the top row above the time.
        """
        self.log.info('render date {0}'.format(date))
        s = self.text_font.size(date)
        x = round(0.5 * self.w - s[0] / 2)
        y = round(0.1 * self.h - s[1] / 2)
        self.log.debug('date p={0},{1},{2}'.format(x, y, s))
        self.screen.fill(self.bg_color, rect=(0.075 * self.w, y, 0.85 * self.w, s[1]))
        surface = self.text_font.render(date, True, color)
        self.screen.blit(surface, (x, y))

    def render_bottom(self, radio_color):
        """
        Draw bottom row elements.
        """
        s = self.text_font.size(self.current_radio)
        x = round(0.075 * self.w)
        y = round(0.9 * self.h - s[1] / 2)
        self.screen.fill(self.bg_color, rect=(x, y, 0.725 * self.w, s[1]))
        for icon in self.icons:
            for label, image in icon.items():
                self.screen.blit(image, (x, y))
                self.ui_event[label] = pygame.Rect(x, y, image.get_width(), image.get_height())
                x += image.get_width() + 8
                if label == 'bright+':
                    x += 40
                # radio station name after the vol- icon
                if label == 'vol-':
                    s = self.text_font.size(self.current_radio)
                    surface = self.text_font.render(self.current_radio, True, radio_color)
                    self.screen.blit(surface, (x, y - 4))
                    self.ui_event['radio'] = pygame.Rect(x, y - 4, surface.get_width(), surface.get_height())
                    x += s[0] + 8

    def render_alarm(self, alarm, color):
        """
        Draw next alarm time in the bottom row below the time.
        """
        self.log.info('render alarm {0}'.format(alarm))
        s = self.text_font.size(alarm)
        x = round(0.925 * self.w - s[0])
        y = round(0.9 * self.h - s[1] / 2)
        self.ui_event["alarm"] = pygame.Rect(x, y, s[0], s[1])
        self.log.debug('alarm p={0},{1}'.format(x, y))
        self.screen.fill(self.bg_color, rect=(0.8 * self.w, y, 0.125 * self.w, s[1]))
        surface = self.text_font.render(alarm, True, color)
        self.screen.blit(surface, (x, y))

    def render_edit(self):
        """
        Draw additional alarm editing elements.
        """
        s = self.text_font.size(self.current_alarm)
        x = round(0.075 * self.w)
        y = round(0.9 * self.h - s[1] / 2)
        self.screen.fill(self.bg_color, rect=(x, y, 0.725 * self.w, s[1]))
        for i in range(7):
            d = calendar.day_abbr[i]
            s = self.text_font.size(d)
            x = round((0.075 + (i + 1) * 0.1) * self.w - s[0])
            y = round(0.9 * self.h - s[1] / 2)
            self.ui_event[d] = pygame.Rect(x, y, s[0], s[1])
            c = self.default_color
            if self.alarm_days[d]:
                c = self.alarm_color
            surface = self.text_font.render(d, True, c)
            self.screen.blit(surface, (x, y))

    def get_ui_action(self, pos):
        """
        Get the UI action for the clicked/touched position.
        """
        result = None
        for id, r in self.ui_event.items():
            if not r.collidepoint(pos):
                continue
            result = id
            break
        return result

    def play(self):
        """
        Play current radio station.
        """

        cmd = 'mpg123 {0}'.format(self.radio_streams[self.current_radio])
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE) 
        with proc.stdout as f:
            while True:
                line = f.readline()
                if not line:
                    break
                self.log.info(line)

    def stop(self):
        """
        Stop current playback.
        """
        mpg123_process = None
        for proc in psutil.process_iter(['pid', 'name']):
            if not 'mpg123' in proc.info['name']:
                continue
            mpg123_process = proc
        if not mpg123_process is None:
            self.log.info('playback process PID {0}'.format(mpg123_process.info['pid']))
            mpg123_process.terminate()

    def run(self):

        last_date = None
        last_time = None
        last_alarm = None
        last_state = None
        last_radio = None

        while True:
            
            now = datetime.datetime.now()
            current_day = now.strftime('%a')
            current_time = now.strftime('%-H:%M')

            #
            # state handling
            #
            if self.state == ClockState.RUN and self.play_process is None and self.alarm_days[current_day] and current_time == self.current_alarm:
                self.log.info('alarm {0} {1} play {2}'.format(current_day, current_time, self.current_radio))
                self.play_process = multiprocessing.Process(target=self.play)
                self.play_start = now
                self.play_process.start()
                self.state = ClockState.ALARM
                last_time = None
            if self.state == ClockState.ALARM and now - self.play_start > datetime.timedelta(seconds=self.alarm_length):
                self.log.info('alarm stop {0}'.format(current_time))
                self.stop()
                self.play_process = None
                self.play_start = None
                self.state = ClockState.RUN
                last_time = None

            for event in pygame.event.get():
                if not event.type is MOUSEBUTTONUP:
                    continue
                pos = pygame.mouse.get_pos()
                if self.rotated_display:
                    # 180 degrees rotated display
                    pos = (self.w - pos[0], self.h - pos[1])
                action = self.get_ui_action(pos)
                self.log.info('event {0} pos {1} action {2}'.format(event.type, pos, action))
                if action == 'alarm':
                    if self.state == ClockState.EDIT:
                        self.state = ClockState.RUN
                        last_time = None
                        last_alarm = None
                    elif self.state == ClockState.RUN:
                        self.state = ClockState.EDIT
                        last_alarm = None
                    elif self.state == ClockState.ALARM:
                        self.state = ClockState.RUN
                        last_time = None
                    self.log.info('state {0}'.format(self.state))
                elif action == 'play':
                    if self.play_process == None:
                        if self.state == ClockState.RUN:
                            self.log.info('play {0}'.format(self.current_radio))
                            self.play_process = multiprocessing.Process(target=self.play)
                            self.play_start = now
                            self.play_process.start()
                    else:
                        self.log.info('stop {0}'.format(self.current_radio))
                        self.stop()
                        self.play_process = None
                        self.play_start = None
                        if self.state == ClockState.ALARM:
                            self.state = ClockState.RUN
                            last_time = None
                    last_radio = None
                elif action == 'radio':
                    if self.state == ClockState.RUN:
                        stations = sorted(self.radio_streams.keys())
                        i = stations.index(self.current_radio)
                        i = (i + 1) % len(stations)
                        self.current_radio = stations[i]
                        self.log.info('new station {0}'.format(self.current_radio))
                        last_radio = None
                elif not action is None:
                    if self.state == ClockState.EDIT:
                        [ hh, mm ] = self.current_alarm.split(':')
                        hh = int(hh)
                        mm = int(mm)
                        if action.startswith('hour'):
                            if action.endswith('+'):
                                hh = (hh + 1) % 24
                            else:
                                hh = (hh - 1) % 24
                        elif action.startswith('min'):
                            if action.endswith('+'):
                                mm = (mm + 1) % 60
                            else:
                                mm = (mm - 1) % 60
                        elif action in self.alarm_days.keys():
                            self.alarm_days[action] = not self.alarm_days[action]
                        self.current_alarm = '{0}:{1:02d}'.format(hh, mm)
                    else:
                        brightness = self.get_brightness()
                        volume = self.get_volume()
                        if action == 'bright-' and brightness > 20:
                            brightness -= 20
                        elif action == 'bright+' and brightness <= 235:
                            brightness += 20
                        elif action == 'vol-' and volume > 10:
                            volume -= 10
                        elif action == 'vol+' and volume <= 150:
                            volume += 10
                        self.set_brightness(brightness)
                        self.set_volume(volume)

            if self.state != last_state:
                self.log.info('state {0}'.format(self.state))
                self.last_radio = None

            if self.state == ClockState.EDIT:
                if self.current_alarm != last_alarm:
                    self.render_time(self.current_alarm, self.alarm_color)
                self.render_edit()
                pygame.display.update()
                last_alarm = self.current_alarm
                last_radio = None
            else:
                current_date = now.strftime('%a %d. %b, %W. Woche')
                if current_date != last_date:
                    c = (self.default_color[0] * 0.75, self.default_color[1] * 0.75, self.default_color[2] * 0.75)
                    self.render_date(current_date, c)
                    pygame.display.update()
                    last_date = current_date

                if current_time != last_time:
                    c = copy.deepcopy(self.default_color)
                    if current_time >= "22:00" and current_time < "7:00":
                        c = copy.deepcopy(self.night_color)
                    if self.state == ClockState.ALARM:
                        c = (self.alarm_color[0], self.alarm_color[1], self.alarm_color[2])
                    self.render_time(current_time, c)
                    pygame.display.update()
                    last_time = current_time

                if self.current_radio != last_radio:
                    c = (self.default_color[0], self.default_color[1], self.default_color[2])
                    if self.play_process != None:
                        c = (0, self.default_color[1], self.default_color[2])
                    if self.state == ClockState.ALARM:
                        c = (self.alarm_color[0], self.alarm_color[1], self.alarm_color[2])
                    self.render_bottom(c)
                    pygame.display.update()
                    last_radio = self.current_radio

                if self.current_alarm != last_alarm:
                    c = (self.alarm_color[0] * 0.75, self.alarm_color[1] * 0.75, self.alarm_color[2] * 0.75)
                    self.render_alarm(self.current_alarm, c)
                    pygame.display.update()
                    last_alarm = self.current_alarm

            last_state = self.state
            
            self.clock.tick(1)
    
if __name__ == '__main__' :
    import argparse
    import json
    import locale

    self = os.path.basename(sys.argv[0])
    myName = os.path.splitext(self)[0]
    log = logging.getLogger(myName)
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    parser = argparse.ArgumentParser(description='Raspberry Pi alarm clock')
    parser.add_argument('-a', '--alarm', default='7:00', help='alarm time')
    parser.add_argument('-d', '--debug', action='store_true', help='debug execution')
    parser.add_argument('--iobroker', default='192.168.137.83:8082', help='iobroker IP address and port')
    parser.add_argument('-L', '--locale', default='de_DE.UTF-8', help='locale')
    parser.add_argument('-r', '--rotated', action='store_false', help='non rotated display (for debugging)')
    parser.add_argument('-s', '--sound', default='', help='alarm sound')
    args = parser.parse_args(sys.argv[1:])

    if args.debug:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)
    locale.setlocale(locale.LC_ALL, args.locale)
    calendar.setfirstweekday(calendar.MONDAY)
 
    clock = AlarmClock(logger=log)
    clock.rotated_display = args.rotated
    clock.current_alarm = args.alarm
    clock.current_radio = 'WDR2'
    clock.run()
