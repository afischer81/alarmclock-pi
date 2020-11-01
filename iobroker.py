#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
       @file: iobroker.py

@description: access to iobroker via python

   @requires: requests
              ciso8601, pytz, tzlocal (for calendar functionality)

     @author: Alexander Fischer

@last change: 2019-06-10
"""

# standard Python modules
import datetime
import json
import logging
from operator import itemgetter
import os
import re
import sys
import time
import uuid

# additional modules
import requests

class IoBroker(object):
    """
    A helper class to connect to an ioBroker instance
    """

    def __init__(self, host, port, logger=None, get_objects=True):
        """
        Initialize the ioBroker connection and get the available objects.
        """
        if logger:
            self.log = logger
        else:
            self.log = logging.getLogger(__name__)
        self.host = host
        self.url = 'http://{0}:{1}/'.format(host, port)
        if get_objects:
            self.objects = self.get_objects()
            self.log.info('{0} objects found in ioBroker on {1}'.format(len(self.objects), host))

    def get_calendar(self, cal_name, cal_class=None):
        """
        Get calendar entries for given calendar name from ioBroker
        Returns dictionary of datetime and event name.
        """
        import ciso8601
        import pytz
        import tzlocal
        import unidecode

        result = {}
        cal = self.get_value('ical.0.data.table')
        if not cal:
            self.log.warning('no ical data table from ioBroker on {0}'.format(args.iobroker))
            return result
        local_tz = tzlocal.get_localzone()
        today = datetime.date.today()
        for ical in cal:
            if not ical['_calName'] == cal_name:
                continue
            self.log.debug('{0} {1} {2}'.format(ical['date'], ical['_date'], unidecode.unidecode(ical['event'])))
            if cal_class != None and not ical['_class'].endswith(cal_class):
                continue
            # convert UTC time to local time
            start = ciso8601.parse_datetime(ical['_date']).replace(tzinfo=pytz.utc).astimezone(local_tz)
            end = ciso8601.parse_datetime(ical['_end']).replace(tzinfo=pytz.utc).astimezone(local_tz)
            dt = start
            if start.date() <= today and end.date() >= today:
                dt = ciso8601.parse_datetime(today.isoformat()).replace(tzinfo=local_tz)
            result[dt] = unidecode.unidecode(ical['event'])
        return result

    def get_objects(self, pattern=None):
        """
        Get objects
        """
        if pattern == None:
            return self.get('objects')
        result = []
        for id in self.objects:
            m = re.match(pattern, id)
            if not m:
                continue
            result.append(self.objects[id])
        self.log.debug('{0} objects found for pattern {1}'.format(len(result), pattern))
        return result

    def get_age(self, object_id):
        """
        Get age of a single ioBroker object value.
        """
        val = self.get('getBulk/' + object_id)[0]
        age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(val['ts'] / 1000)).total_seconds()
        return age

    def get_value(self, object_id):
        """
        Get a single ioBroker object value.
        """
        return self.get('getPlainValue/' + object_id)

    def get_bulk_value(self, object_id, with_age=False):
        """
        Get a single ioBroker object value.
        """
        bulk = self.get('getBulk/' + object_id)
        if with_age:
            bulk[0]['age'] = (datetime.datetime.now() - datetime.datetime.fromtimestamp(bulk[0]['ts'] / 1000)).total_seconds()
        return bulk

    def get_values(self, object_ids):
        """
        Get ioBroker object values.
        """
        result = {}
        self.log.debug('get_values() start')
        for id in object_ids:
            value = self.get('get/' + id)
            if value == None:
                continue
            result[id] = value
        self.log.debug('get_values() finish')
        return result

    def set_value(self, value, events=True):
        """
        Set ioBroker object values.
        """
        self.log.debug('set_value() start')
        result = False
        if not value is None:
            if events:
                self.post('setBulk/?' + value)
            else:
                [ id, state ] = value.split('=')
                cmd = 'ssh pi@{0} sudo iobroker state set {1} {2}'.format(self.host, id, state)
                os.system(cmd)
        self.log.debug('set_value() finish')
        return result

    def set_values(self, values):
        """
        Set ioBroker object values.
        """
        self.log.debug('set_values() start')
        result = False
        if len(values) > 0:
            self.post('setBulk/?' + '&'.join(values))
        self.log.debug('set_values() finish')
        return result

    def toggle_value(self, value):
        """
        Toggle ioBroker object value.
        """
        self.log.debug('toggle_value() start')
        result = False
        self.get('toggle/' + value)
        self.log.debug('toggle_value() finish')
        return result

    def get(self, url):
        """
        Generic GET method.
        """
        result = None
        self.log.debug('get({0}) start'.format(self.url + url))
        try:
            response = requests.get(self.url + url)
            if response.status_code == 200:
                result = response.json()
            else:
                self.log.debug('status {0}: {1}'.format(response.status_code, response.text))
        except:
            self.log.critical('ioBroker connection to {0} failed'.format(self.url))
            pass
        self.log.debug('get() finish')
        return result

    def post(self, url):
        """
        Generic POST method.
        """
        result = None
        try:
            response = requests.post(self.url + url)
            result = response.status_code == 200
        except:
            self.log.critical('ioBroker connection to {0} failed'.format(self.url))
            pass
        return result

if __name__ == '__main__':
    import argparse

    self = os.path.basename(sys.argv[0])
    myName = os.path.splitext(self)[0]
    log = logging.getLogger(myName)
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    parser = argparse.ArgumentParser(description='iobroker database')
    parser.add_argument('-d', '--debug', action='store_true', help='debug execution')
    parser.add_argument('-H', '--host', default='192.168.137.83', help='iobroker hostname')
    parser.add_argument('--age', default='', help='get age of a datapoint value')
    parser.add_argument('--value', default='', help='get datapoint value')
    parser.add_argument('-p', '--port', type=int, default=8082, help='iobroker REST API port')
    args = parser.parse_args(sys.argv[1:])

    if args.debug:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)
    iobroker = IoBroker(args.host, args.port, logger=log, get_objects=False)
    if args.age:
        print('{0:.0f}'.format(iobroker.get_age(args.age)))
    if args.value:
        print(iobroker.get_value(args.value))
