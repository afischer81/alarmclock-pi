#!/usr/bin/env python3

# standard Python modules
#import calendar
#import copy
#import datetime
#import dateutil
#import enum
import glob
import json
import logging
#import multiprocessing
import os
import platform
#import re
#import signal
#import subprocess
#import sys

import pygame
from pygame.locals import *

class PygameUi:
    """
    Base class for UIs based on pygame
    """

    def __init__(self, size=(800,480), logger=None) :
        if logger:
            self.log = logger
        else:
            self.log = logging.getLogger(__name__)

        self.bg_color = (0, 0, 0)
        self.default_color = (255, 255, 255)
        self.rotated_display = True

        self.system = platform.machine().lower()
        self.log.info('running on an {0} system'.format(self.system))
        if self.system.startswith('arm'):
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
        self.screen = pygame.display.set_mode(size, DOUBLEBUF)

        # Clear the screen to start
        self.screen.fill(self.bg_color)
        # Initialise font support
        pygame.font.init()
        # Render the screen
        pygame.display.update()

        if self.system.startswith('arm'):
            self.rotated_display = True
            pygame.mouse.set_visible(False)
        self.w, self.h = self.screen.get_size()
        self.log.info('Screen size: %d x %d' % (self.w, self.h))
        self.clock = pygame.time.Clock()

        if self.system.startswith('arm'):
            self.text_font = pygame.font.Font('/usr/share/fonts/truetype/freefont/FreeSansBold.ttf', round(self.h * 0.08))
        elif self.system.startswith('amd'):
            font_path = pygame.font.match_font('arial')
            self.text_font = pygame.font.Font(font_path, round(self.h * 0.08))

        self.menu = {}
        for f in glob.glob('menu_*.json'):
            label = os.path.splitext(os.path.basename(f))[0].split('_')[1]
            self.log.info('reading menu {} from {}'.format(label, f))
            self.menu[label] = self.read_menu(f)
            self.log.info('{} elements in menu {}'.format(len(self.menu[label]), label))

    def clear(self, x, y, w, h):
        """
        Clear a rectangular area of the screen.
        """
        self.screen.fill(self.bg_color, rect=(x * self.w, y * self.h, w * self.w, h * self.h))

    def get_menu_element(self, menu, name):
        """
        Get menu element.
        """

        result = None
        for elem in self.menu[menu]:
            if elem['name'] == name:
                result = elem
                break
        return result

    def get_menu_element_index(self, menu, name):
        """
        Get menu element.
        """

        result = None
        for i in range(len(self.menu[menu])):
            if self.menu[menu][i]['name'] == name:
                result = i
                break
        return result

    def get_ui_action(self, pos, menus=['bottom']):
        """
        Get the UI elem for the clicked/touched position.
        """
        result = None
        for menu in menus:
            for elem in self.menu[menu]:
                if not 'rect' in elem.keys():
                    continue
                if not elem['rect'].collidepoint(pos):
                    continue
                result = elem
                break
        return result

    def read_menu(self, file_name):
        """
        Read menu configuration from a JSON file.
        """

        with open(file_name) as f:
            menu = json.load(f)
        for elem in menu:
            if not 'name' in elem.keys():
                self.log.error('menu elements must have a name')
                continue
            if not 'label' in elem.keys() or not elem['label']:
                elem['label'] = elem['name']
            if 'icon' in elem.keys():
                elem['icon'] = pygame.image.load(elem['icon'])
                if 'size' in elem.keys():
                    elem['icon'] = pygame.transform.scale(elem['icon'], tuple(elem['size']))
        return menu

    def render_top(self, date, color):
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

    def render_bottom(self, menu='bottom', dx=24):
        """
        Draw bottom row elements.
        """
        s = self.text_font.size('ABC')
        x = round(0.075 * self.w)
        y = round(0.925 * self.h)
        self.screen.fill(self.bg_color, rect=(x, y - s[1] / 2 - 2, 0.825 * self.w, s[1] + 4))
        self.log.debug('rendering menu {} with {} elements'.format(menu, len(self.menu[menu])))
        self.log.debug(json.dumps(self.menu[menu], indent=2, default=str))
        w = 0
        for elem in self.menu[menu]:
            elem_width = 0
            if 'pos' in elem.keys():
                continue
            if 'icon' in elem.keys():
                elem_width = elem['icon'].get_width()
            else:
                if 'label' in elem.keys():
                    label = elem['label']
                else:
                    label = elem['name']
                if not label == 'NONE':
                    elem_width = self.text_font.size(label)[0]
            if elem_width > 0:
                w += elem_width + dx
        x = round(0.5 * self.w - (w - dx) / 2)
        for elem in self.menu[menu]:
            if 'pos' in elem.keys():
                x = elem['pos'][0]
                if x < 1.0:
                    x *= self.w
                y = elem['pos'][1]
                if y < 1.0:
                    y *= self.h
            if 'icon' in elem.keys():
                img = elem['icon']
                ix = x - img.get_width() / 2
                iy = y - img.get_height() / 2
                self.screen.blit(img, (ix, iy))
                elem['rect'] = pygame.Rect(ix, iy, img.get_width(), img.get_height())
                x += img.get_width() + dx
            else:
                if 'label' in elem.keys():
                    label = elem['label']
                else:
                    label = elem['name']
                color = self.default_color
                if 'color' in elem.keys():
                    color = elem['color']
                align = 'cc'
                if align in elem.keys():
                    align = elem['align']
                if not label == 'NONE':
                    rect = self.render_text(x, y, label, color=color, align=align)
                    elem['rect'] = pygame.Rect(rect[0], rect[1], rect[2], rect[3])
                    x += rect[2] + 24

    def render_text(self, x, y, text, color=None, align='cc'):
        """
        Render text at a given position with color and horizontal/vertical alignment.
        """
        tx = x
        if x < 1.0:
            tx = round(x * self.w)
        ty = y
        if y < 1.0:
            ty = round(y * self.h)
        s = self.text_font.size(text)
        if align[0] == 'c':
            tx -= s[0] / 2
        elif align[0] == 'r':
            tx -= s[0]
        if align[1] == 'c':
            ty -= s[1] / 2
        elif align[1] == 't':
            ty -= s[1]
        if color is None:
            color = self.default_color
        self.screen.fill(self.bg_color, rect=(tx, ty, s[0], s[1]))
        surface = self.text_font.render(text, True, color)
        self.screen.blit(surface, (tx, ty))
        return (tx, ty, s[0], s[1])

    def set_brightness(self, value):
        """
        Set the the panel brightness to value (0- 255).
        """
        self.log.info('set_brightness({0})'.format(value))
        current_brightness = self.get_brightness()
        if value == current_brightness:
            return
        if not os.path.exists('/sys/class/backlight/rpi_backlight/brightness'):
            return
        with open('/sys/class/backlight/rpi_backlight/brightness', 'w') as f:
            f.write('{0}'.format(value))

    def get_brightness(self):
        """
        Get the current panel brightness (0 - 255).
        """
        value = 0
        if not os.path.exists('/sys/class/backlight/rpi_backlight/actual_brightness'):
            return value
        with open('/sys/class/backlight/rpi_backlight/actual_brightness') as f:
            value = int(f.read())
        self.log.info('get_brightness() {0}'.format(value))
        return value
