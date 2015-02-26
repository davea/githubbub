#!/usr/bin/env python
import time
import os
from operator import attrgetter
from itertools import islice
from datetime import date

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

    def add_events(self, events):
        pass

    def render(self):
        pass


class StreamView(BaseView):
    def __init__(self, manager):
        self.manager = manager
        self.events = []

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

    def add_events(self, events):
        today = date.today()
        filtered_events = [
            e
            for e
            in events[-self.max_events:]
            if e.created_at.date() == today
        ]
        for event in filtered_events:
            self.add_event(event)
        print "Added {} new events to StreamView".format(len(filtered_events))

    def add_event(self, event):
        if len(self.events) >= ROWS * COLS:
            new_length = COLS * (ROWS - 1)
            self.events = self.events[-new_length:]
        self.events.append(event)
        self.events.sort(key=attrgetter('created_at'))

    def render(self):
        if not self.events:
            return
        print "Rendering events:"
        unicornhat.clear()
        count = ROWS * COLS
        for i, event in enumerate(self.events[-count:]):
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
        self.view = StreamView(manager=self)
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
