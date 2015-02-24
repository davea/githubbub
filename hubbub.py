#!/usr/bin/env python
import time
import os
from operator import attrgetter

import unicornhat
from github3 import login
import yaml
import tinycss.color3

from attrdict import AttrDict

COLS = 8
ROWS = 8

class StreamView(object):
    def __init__(self, manager):
        self.manager = manager
        self.events = []

    def _parse_colour(self, colour):
        """Parse a CSS colour into a unicornhat-friendly (r, g, b) tuple"""
        r, g, b, _ = [int(round(255*v)) for v in tinycss.color3.parse_color_string(colour)]
        return r, g, b

    def _event_colour(self, event):
        """Gets a (r,g,b) colour tuple for the current event, based on its type."""
        colour = self.manager.config.EVENT_COLOURS.get(event.type[:-5], "black")
        r, g, b = self._parse_colour(colour)
        # Brighten events by the logged-in user
        if event.actor == self.manager.user:
            r, g, b = [min(255, int(round(v*1.5))) for v in (r, g, b)]
        return r, g, b

    def add_events(self, events):
        if events:
            self.events += events
            self.events.sort(key=attrgetter('id'))
            print "Added {} new events to StreamView".format(len(events))

    def render(self):
        if not self.events:
            return
        print "Rendering events:"
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
        self.events_iterator = self.user.iter_org_events(self.config.GITHUB_ORG)
        self.view = StreamView(manager=self)
        self.all_events = []
        self.seen_events = set()

    def _load_new_events(self):
        print "Loading events:"
        new_events = [e for e in self.events_iterator if e not in self.seen_events]
        self.all_events += new_events
        self.seen_events.update()
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
    """Logs into GitHub API with the token from config.yml and returns a User object."""
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
