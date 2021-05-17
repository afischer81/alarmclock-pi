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

from iobroker import *
from pygame_ui import *

class ClockState(enum.Enum):
    RUN = 1
    ALARM = 2
    EDIT = 3

class AlarmClock(PygameUi):
    """
    Alarmclock for Raspberry Pi 7" touch screen display
    """

    def __init__(self, size=(800,480), config=None, iobroker=None, logger=None) :
        PygameUi.__init__(self, size, logger)

        self.alarm_volume = [ 50, 90 ]
        self.alarm_length = [ 60, 300 ] # volume rise period, total alarm length in seconds
        self.next_alarm = '--:--'
        self.manual_alarm = False

        self.config_file_name = config
        self.config = self.read_config(config)

        self.iobroker = None
        if not iobroker is None:
            (host, ip) = iobroker.split(':')
            self.iobroker = IoBroker(host, int(ip), logger=self.log, get_objects=False)

        self.rotated_display = True
        self.default_color = (255, 255, 255)
        self.night_color = (48, 48, 48)
        self.alarm_color = (192, 0, 0)
        self.bg_color = (0, 0, 0)
        self.ui_event = {}
        self.state = ClockState.RUN

        self.radio_streams = []
        self.play_start = None

        self.play_process = None
        self.get_volume_cmd = 'amixer get \'PCM,0\''
        self.set_volume_cmd = 'amixer set \'PCM,0\' {0}%'

        self.time_font = pygame.font.Font('font/gluqlo.ttf', round(self.h * 0.64))

        self.menu['bottom'].append({ 'name': 'station', 'label': self.config['current_stream'], 'pos': (0.08, 0.925), 'color': self.default_color, 'align':'lc' })
        self.menu['bottom'].append({ 'name': 'alarm', 'label': self.next_alarm, 'pos': (0.925, 0.925), 'color': self.alarm_color, 'align':'rc' })
        self.menu['edit'].append(self.menu['bottom'][-1])

        self.set_brightness(self.config['brightness'])

    def read_config(self, file_name):
        config = {}
        if file_name is None or not os.path.exists(file_name):
            self.log.warning('no config file or config file not found')
            return config
        with open(file_name) as f:
            config = json.load(f)
        if 'alarm_length' in config.keys():
            self.alarm_length = config['alarm_length']
        if 'alarm_volume' in config.keys():
            self.alarm_volume = config['alarm_volume']
        if 'current_stream' in config.keys():
            self.current_radio = config['current_stream']
        return config

    def write_config(self):
        with open(self.config_file_name, 'w') as f:
            json.dump(self.config, f)

    def set_volume(self, value):
        if not self.system.startswith('arm'):
            return
        self.log.info('set_volume({0})'.format(value))
        current_volume = self.get_volume()
        if value == current_volume:
            return
        os.system(self.set_volume_cmd.format(value))

    def get_volume(self):
        value = 0
        if not self.system.startswith('arm'):
            return value
        with subprocess.Popen(self.get_volume_cmd, shell=True, stdout=subprocess.PIPE).stdout as f:
            for line in f.readlines():
                m = re.search('(\d+)%', line.decode('utf-8'))
                if m:
                    value = int(m.group(1))
        return value

    def render_time(self, time, color, menu=None):
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
        if not menu is None:
            i = self.get_menu_element_index(menu, 'hour+')
            if not i is None:
                self.menu[menu][i]['rect'] = pygame.Rect(x, y, s[0], s[1] / 2)
            i = self.get_menu_element_index(menu, 'hour-')
            if not i is None:
                self.menu[menu][i]['rect'] = pygame.Rect(x, y + s[1] / 2, s[0], s[1] / 2)
            self.log.debug('hh p={0},{1},{2}'.format(x, y, s))
        surface = self.time_font.render(hh, True, color)
        self.screen.blit(surface, (x, y))
        s = self.time_font.size(mm)
        x = round((0.925 - 0.2) * self.w - s[0] / 2)
        y = round(0.5 * self.h - s[1] / 2)
        if not menu is None:
            i = self.get_menu_element_index(menu, 'min+')
            if not i is None:
                self.menu[menu][i]['rect'] = pygame.Rect(x, y, s[0], s[1] / 2)
            i = self.get_menu_element_index(menu, 'min-')
            if not i is None:
                self.menu[menu][i]['rect'] = pygame.Rect(x, y + s[1] / 2, s[0], s[1] / 2)
            self.log.debug('mm p={0},{1},{2}'.format(x, y, s))
        surface = self.time_font.render(mm, True, color)
        self.screen.blit(surface, (x, y))
        self.screen.fill(self.bg_color, rect=(0.075 * self.w, 0.495 * self.h, 0.85 * self.w, 0.01 * self.h))
        self.screen.fill(self.bg_color, rect=(0.49 * self.w, 0.18 * self.h, 0.02 * self.w, 0.64 * self.h))

    def render_temp(self, temp1, temp2, color):
        """
        Draw the current temperatures in top corners.
        """
        self.log.info('render temp {} {}'.format(temp1, temp2))
        y = round(0.1 * self.h)
        if not temp1 is None:
            t1 = '-'
            try:
                t1 = '{:.1f}°C'.format(float(temp1))
            except:
                pass
            s = self.text_font.size(t1)
            self.screen.fill(self.bg_color, rect=(0, y - s[1] / 2, 0.175 * self.w, s[1]))
            self.render_text(0.025 * self.w, y, t1, color=color, align='lc')
        if not temp2 is None:
            t2 = '-'
            try:
                t2 = '{:.1f}°C'.format(float(temp2))
            except:
                pass
            s = self.text_font.size(t2)
            self.screen.fill(self.bg_color, rect=(0.825 * self.w, y - s[1] / 2, 0.175 * self.w, s[1]))
            self.render_text(0.975 * self.w, y, t2, color=color, align='rc')

    def get_temp(self, ids):
        """
        Get temperatures from ioBroker datapoints.
        """
        result = []
        for id in ids:
            result.append('-')
            try:
                temp = self.iobroker.get_bulk_value(id, with_age=True)
                if temp[0]['age'] < 1200:
                    result[-1] = temp[0]['val']
            except:
                pass
        return result

    def render_alarm(self, alarm, color, menu=None):
        """
        Draw next alarm time in the bottom row below the time.
        """
        self.log.info('render alarm {0}'.format(alarm))
        self.render_time(alarm, color, menu)

    def update_alarms(self, id='javascript.0.rooms.sz.alarm'):
        """
        Update alarms from iobroker entry.
        """
        alarm = self.iobroker.get_value(id)
        if alarm:
            log.info('new alarms from {} {}'.format(id, alarm))
            self.write_config()
        else:
            alarm = '--:--'
        return alarm

    def play(self):
        """
        Play current radio station.
        """

        if not self.system.startswith('arm'):
            return
        cmd = 'mpg123 {0}'.format(self.config['streams'][self.current_radio])
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

        if not self.system.startswith('arm'):
            return
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
        self.next_alarm = self.update_alarms()
        self.edit_alarm = None
        last_state = None
        last_radio = None
        last_menu = None
        last_temp = [ None, None ]
        [ temp1, temp2 ] = self.get_temp(self.config['temperatures'])
        current_menu = 'bottom'
        keep_running = True
        tick = 0

        while keep_running:

            now = datetime.datetime.now()
            current_day = now.strftime('%a')
            current_time = now.strftime('%-H:%M')
            if now.hour >= 6 and now.hour <= 23 and (now.minute == 23 or now.minute == 53) and tick == 2:
                if not self.manual_alarm:
                    self.next_alarm = self.update_alarms()
            self.menu['bottom'][-1]['label'] = self.next_alarm
            if now.hour == 22 and now.minute == 13 and tick == 2:
                self.set_brightness(10)
                self.render_bottom(current_menu, default_color=self.night_color)
                last_date = None
            if (now.minute % 5) == 0 and tick == 2:
                [ temp1, temp2 ] = self.get_temp(self.config['temperatures'])

            #
            # state handling
            #
            if self.state == ClockState.RUN and self.play_process is None and self.next_alarm == current_time:
                self.log.info('alarm {0} {1} play {2}'.format(current_day, current_time, self.current_radio))
                self.set_volume(self.alarm_volume[0])
                self.set_brightness(50)
                self.play_process = multiprocessing.Process(target=self.play)
                self.play_start = now
                if self.system.startswith('arm'):
                    self.play_process.start()
                self.state = ClockState.ALARM
                last_time = None
            if self.state == ClockState.ALARM:
                alarm_duration = now - self.play_start
                if alarm_duration > datetime.timedelta(seconds=self.alarm_length[1]):
                    self.log.info('alarm stop {0}'.format(current_time))
                    self.stop()
                    self.play_process = None
                    self.play_start = None
                    self.state = ClockState.RUN
                    last_time = None
                elif alarm_duration < datetime.timedelta(seconds=self.alarm_length[0]):
                    volume = self.alarm_volume[0] + (self.alarm_volume[1] - self.alarm_volume[0]) * alarm_duration.total_seconds() / self.alarm_length[0]
                    self.set_volume(volume)

            for event in pygame.event.get():
                # exit on any key press on non ARM systems (development mode)
                if not self.system.startswith('arm') and event.type == pygame.KEYDOWN:
                    keep_running = False
                if not event.type is MOUSEBUTTONUP:
                    continue
                pos = pygame.mouse.get_pos()
                if self.rotated_display:
                    # 180 degrees rotated display
                    pos = (self.w - pos[0], self.h - pos[1])
                elem = self.get_ui_action(pos, [ current_menu ])
                if not elem is None:
                    self.log.info('event {0} pos {1} elem {2}'.format(event.type, pos, elem))
                    if elem['name'] == 'alarm':
                        if self.state == ClockState.EDIT:
                            self.state = ClockState.RUN
                            current_menu = 'bottom'
                            last_menu = None
                            self.next_alarm = self.edit_alarm
                            self.menu['bottom'][-1]['label'] = self.next_alarm
                            self.manual_alarm = True
                            last_time = None
                            last_alarm = None
                        elif self.state == ClockState.RUN:
                            self.state = ClockState.EDIT
                            self.edit_alarm = self.next_alarm
                            if self.edit_alarm == '--:--':
                                self.edit_alarm = '7:00'
                            last_alarm = None
                            current_menu = 'edit'
                            last_menu = None
                        elif self.state == ClockState.ALARM:
                            self.state = ClockState.RUN
                            last_time = None
                        self.log.info('state {0}'.format(self.state))
                    elif elem['name'] == 'cancel':
                        if self.state == ClockState.EDIT:
                            self.state = ClockState.RUN
                            self.next_alarm = '--:--'
                            self.menu['bottom'][-1]['label'] = self.next_alarm
                            last_alarm = None
                            last_time = None
                            current_menu = 'bottom'
                            self.manual_alarm = False
                    elif elem['label'] == 'play':
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
                    elif elem['label'] == 'radio':
                        if self.state == ClockState.RUN:
                            stations = sorted(self.config['streams'].keys())
                            i = stations.index(self.current_radio)
                            i = (i + 1) % len(stations)
                            self.current_radio = stations[i]
                            self.log.info('new station {0}'.format(self.current_radio))
                            last_radio = None
                    elif not elem['label'] is None:
                        if self.state == ClockState.EDIT:
                            [ hh, mm ] = self.edit_alarm.split(':')
                            hh = int(hh)
                            mm = int(mm)
                            if elem['name'].startswith('hour'):
                                if elem['name'].endswith('+'):
                                    hh = (hh + 1) % 24
                                else:
                                    hh = (hh - 1) % 24
                            elif elem['name'].startswith('min'):
                                if elem['name'].endswith('+'):
                                    mm = (mm + 1) % 60
                                else:
                                    mm = (mm - 1) % 60
                            self.edit_alarm = '{0}:{1:02d}'.format(hh, mm)
                            self.log.info('edit_alarm {}'.format(self.edit_alarm))
                            last_alarm = None
                        else:
                            brightness = self.get_brightness()
                            volume = self.get_volume()
                            if elem['label'] == 'bright-' and brightness >= 20:
                                brightness -= 10
                            elif elem['label'] == 'bright+' and brightness <= 245:
                                brightness += 10
                            elif elem['label'] == 'vol-' and volume > 10:
                                volume -= 10
                            elif elem['label'] == 'vol+' and volume <= 150:
                                volume += 10
                            self.set_brightness(brightness)
                            self.set_volume(volume)

            if self.state != last_state:
                self.log.info('state {} menu {}'.format(self.state, current_menu))
                self.last_radio = None
            do_update = False

            if self.state == ClockState.EDIT:
                if self.edit_alarm != last_alarm:
                    self.render_time(self.edit_alarm, self.alarm_color, current_menu)
                do_update = True
                last_alarm = self.edit_alarm
                last_radio = None
            else:
                current_date = now.strftime('%a %d. %b, %W. Woche')
                if current_date != last_date:
                    c = (self.default_color[0] * 0.75, self.default_color[1] * 0.75, self.default_color[2] * 0.75)
                    if now.hour >= 22 or now.hour <= 6:
                        c = (self.night_color[0], self.night_color[1], self.night_color[2])
                    self.render_top(current_date, c)
                    do_update = True
                    last_date = current_date

                if temp1 != last_temp[0] or temp2 != last_temp[1]:
                    c = (self.default_color[0] * 0.75, self.default_color[1] * 0.75, self.default_color[2] * 0.75)
                    if now.hour >= 22 or now.hour <= 6:
                        c = (self.night_color[0], self.night_color[1], self.night_color[2])
                    self.render_temp(temp1, temp2, color=c)
                    do_update = True
                    last_temp[0] = temp1
                    last_temp[1] = temp2

                if current_time != last_time:
                    c = copy.deepcopy(self.default_color)
                    if now.hour >= 22 or now.hour <= 6:
                        c = (self.night_color[0], self.night_color[1], self.night_color[2])
                    if self.state == ClockState.ALARM:
                        c = (self.alarm_color[0], self.alarm_color[1], self.alarm_color[2])
                    self.render_time(current_time, c)
                    do_update = True
                    last_time = current_time

                if self.current_radio != last_radio:
                    c = (self.default_color[0], self.default_color[1], self.default_color[2])
                    if self.play_process != None:
                        c = (0, self.default_color[1], self.default_color[2])
                    if self.state == ClockState.ALARM:
                        c = (self.alarm_color[0], self.alarm_color[1], self.alarm_color[2])
                    do_update = True
                    last_radio = self.current_radio

            if self.next_alarm != last_alarm:
                self.render_bottom(current_menu)
                last_alarm = self.next_alarm

            if current_menu != last_menu:
                self.render_bottom(current_menu)
                last_menu = current_menu

            if do_update:
                pygame.display.update()

            last_state = self.state
            
            self.clock.tick(1)
            tick = (tick + 1) % 60
    
if __name__ == '__main__' :
    import argparse
    import json
    import locale

    self = os.path.basename(sys.argv[0])
    myName = os.path.splitext(self)[0]
    log = logging.getLogger(myName)
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    parser = argparse.ArgumentParser(description='Raspberry Pi alarm clock')
    parser.add_argument('-c', '--config', default='alarmclock.json', help='config file')
    parser.add_argument('-d', '--debug', action='store_false', help='debug execution')
    parser.add_argument('--iobroker', default='192.168.137.83:8082', help='iobroker IP address and port')
    parser.add_argument('-L', '--locale', default='de_DE.UTF-8', help='locale')
    parser.add_argument('-r', '--rotated', action='store_false', help='non rotated display (for debugging)')
    args = parser.parse_args(sys.argv[1:])

    if args.debug:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)
    locale.setlocale(locale.LC_ALL, args.locale)
    calendar.setfirstweekday(calendar.MONDAY)
 
    ui = AlarmClock(config=args.config, iobroker=args.iobroker, logger=log)
    ui.rotated_display = args.rotated
    ui.run()
