#!/usr/bin/env python
import time
import os
from operator import attrgetter
from itertools import islice
from datetime import date, datetime
from collections import defaultdict, Counter
from math import floor
import colorsys
from random import randint

import unicornhat
from github3 import login
import yaml
import tinycss.color3
from requests.exceptions import RequestException

from attrdict import AttrDict

COLS = 8
ROWS = 8


class BaseView(object):
    max_events = COLS * ROWS
    today_only = False

    def __init__(self, manager):
        self.manager = manager
        self.events = []

    def add_events(self, events):
        if self.today_only:
            today = date.today()
            events = [
                e
                for e
                in events
                if e.created_at.date() == today
            ]
        for event in events:
            self.add_event(event)

    def add_event(self, event):
        self.events.append(event)

    def render(self):
        pass


class PunchcardView(BaseView):
    """
    Displays recent activity in a similar manner to GitHub's punch card, e.g.:
    https://github.com/mysociety/pombola/graphs/punch-card
    Each row represents one wallclock-hour of activity, divided into as
    many equal blocks as there are columns.
    The most recent hour is at the bottom.
    """
    max_events = None
    today_only = True
    hue = None

    def __init__(self, *args, **kwargs):
        super(PunchcardView, self).__init__(*args, **kwargs)
        self.hue = randint(0, 359)

    def _get_punchcard(self):
        punchcard = defaultdict(Counter)
        for event in self.events:
            created_at = event.created_at
            hour = created_at.hour
            minute = created_at.minute + (created_at.second / 60.0)
            x = int(floor(minute/(60.0/COLS)))
            punchcard[hour][x] += 1
        return punchcard

    def render(self):
        print "PunchcardView.render:"
        punchcard = self._get_punchcard()
        max_value = max(v for row in punchcard.values() for v in row.values())
        max_value = float(max_value)
        end = datetime.utcnow().hour + 1
        start = end - ROWS
        # Boost pixel brightness by this much so quiet times are still visible
        boost = 0.075
        unicornhat.clear()
        # Do a bit of colour cycling to indicate an update
        new_hue = randint(0, 359)
        for hue in range(min(self.hue, new_hue), max(self.hue, new_hue)+1):
            for hour in range(start, end):
                y = hour - start
                for x in range(COLS):
                    h = hue / 360.0
                    s = 1.0
                    # Cap lightness so the brightest pixel isn't quite white
                    v = min(0.8, punchcard[hour][x] / max_value)
                    # Give the value a little boost if it's above 0
                    if v > 0:
                        v = (v * (1 - boost)) + boost
                    # Convert our 0-1 HSL values into 0-255 RGB for display
                    r, g, b = colorsys.hls_to_rgb(h, v, s)
                    r, g, b = (int(round(i * 255)) for i in (r, g, b))
                    unicornhat.set_pixel(x, y, r, g, b)
            unicornhat.show()
        self.hue = new_hue
        print "   done."


class StreamView(BaseView):
    """
    Renders events in a stream across the display, which slowly
    scrolls upwards as new events occur.
    """
    today_only = True

    def _parse_colour(self, colour):
        """Parse a CSS colour into a unicornhat-friendly (r, g, b) tuple"""
        r, g, b, _ = [
            int(round(255*v))
            for v
            in tinycss.color3.parse_color_string(colour)
        ]
        return r, g, b

    def _get_complex_colour(self, event, rules):
        """
        Gets a (r,g,b) colour tuple for an event with a complex set of
        rules defined in config.yml
        """
        for key in rules:
            if key not in event.payload:
                continue
            for value, colour in rules[key].items():
                if event.payload[key] == value:
                    override = self._get_override_colour(event, rules)
                    if override:
                        colour = override
                    return self._parse_colour(colour)

    def _get_override_colour(self, event, rules):
        """
        This is a hack to enable certain events to be coloured based on rules
        more complex than we can reasonably express in config.yml
        """
        # Pull requests that have been closed and merged:
        if (event.type == "PullRequestEvent" and
                event.payload['action'] == 'closed' and
                event.payload['pull_request'].merged_at is not None and
                rules.get('action', {}).get('merged') is not None):
            return rules['action']['merged']

    def _event_colour(self, event):
        """
        Gets a (r,g,b) colour tuple for the current event, based on its type.
        """
        etype = event.type[:-5]
        colour = self.manager.config.EVENT_COLOURS.get(etype, "black")
        if isinstance(colour, basestring):
            r, g, b = self._parse_colour(colour)
        else:
            # Some events, such as issues being opened/closed, have a more
            # complex set of rules to define their colour
            r, g, b = self._get_complex_colour(event, colour)
        # Brighten events by the logged-in user
        if event.actor == self.manager.user:
            r, g, b = [min(255, int(round(v*1.5))) for v in (r, g, b)]
        return r, g, b

    def add_event(self, event):
        # If the display is full up, chop a line off
        # the top to make space at the bottom for new events
        if len(self.events) >= ROWS * COLS:
            new_length = COLS * (ROWS - 1)
            self.events = self.events[-new_length:]
        return super(StreamView, self).add_event(event)

    def render(self):
        print "StreamView.render:"
        unicornhat.clear()
        # Because we render one event per-pixel, we need to only
        # render the most recent self.max_events events
        start = self.max_events * -1
        for i, event in enumerate(self.events[start:]):
            x = i % COLS
            y = i // ROWS
            r, g, b = self._event_colour(event)
            unicornhat.set_pixel(x, y, r, g, b)
        unicornhat.show()
        print "   done."


class EventsManager(object):
    seen_events = None
    all_events = None

    def __init__(self, config, user):
        self.config = config
        self.user = user
        self.view = PunchcardView(manager=self)
        self.all_events = []
        self.seen_event_ids = set()
        org = self.config.GITHUB_ORG
        self.events_iterator = self.user.iter_org_events(org)

    def _load_new_events(self):
        print "Loading events:"
        try:
            new_events = [
                e
                for e
                in islice(self.events_iterator, self.view.max_events)
                if e.id not in self.seen_event_ids
            ]
        except RequestException:
            print "   failed."
            return []
        new_events.sort(key=attrgetter('created_at'))
        self.all_events += new_events
        self.seen_event_ids.update(set([e.id for e in new_events]))
        self.events_iterator.refresh(True)
        print "   done. {} available".format(len(self.all_events))
        return new_events

    def run(self):
        while True:
            new_events = self._load_new_events()
            if new_events:
                self.view.add_events(new_events)
                self.view.render()
            time.sleep(self.config.REFRESH_SECONDS)


def load_config():
    """Load contents of config.yml into an AttrDict"""
    print "Loading config:"
    config_yml = os.path.join(os.path.dirname(__file__), "config.yml")
    if not os.path.exists(config_yml):
        raise Exception("config.yml is missing")
    with open(config_yml) as f:
        config = AttrDict(yaml.load(f))
    print "   done."
    return config


def setup_unicorn(config):
    """Initialise unicornhat module with brightness and rotation from config"""
    print "Setting up Unicorn HAT:"
    unicornhat.brightness(config.BRIGHTNESS)
    unicornhat.rotation(config.ROTATION)
    print "   done."


def github_login(config):
    """
    Logs into GitHub API with the token from config.yml
    and returns a User object.
    """
    print "Github API login:"
    gh = login(token=config.GITHUB_TOKEN)
    user = gh.user()
    print "   done."
    return user


def main():
    config = load_config()
    setup_unicorn(config)
    user = github_login(config)

    manager = EventsManager(config, user)
    manager.run()

if __name__ == '__main__':
    main()
