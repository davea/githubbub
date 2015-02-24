#!/usr/bin/env python
import time
import os
from itertools import islice

import unicornhat
from github3 import login
import yaml
import tinycss.color3

config = None

COLS = 8
ROWS = 8

class EventPixel(object):
    def __init__(self, event, user):
        self.event = event
        self.user = user

    @property
    def rgb(self):
        """Gets a (r,g,b) colour tuple for the current event, based on its type."""
        colour = config.EVENT_COLOURS.get(self.event.type[:-5], "black")
        r, g, b = parse_colour(colour)
        # Brighten events by the logged-in user
        if self.event.actor == self.user:
            r, g, b = [min(255, int(round(v*1.5))) for v in (r, g, b)]
        return r, g, b

def parse_colour(colour):
    """Parse a CSS colour into a unicornhat-friendly (r, g, b) tuple"""
    r, g, b, _ = [int(round(255*v)) for v in tinycss.color3.parse_color_string(colour)]
    return r, g, b

def load_config():
    """Load contents of config.yml into global config object"""
    print "Loading config:"
    global config
    config_yml = os.path.join(os.path.dirname(__file__), "config.yml")
    if not os.path.exists(config_yml):
        raise Exception("config.yml is missing")
    with open(config_yml) as f:
        config = AttrDict(yaml.load(f))
    print "   done."

def setup_unicorn():
    """Initialise unicornhat module with brightness and rotation from config"""
    print "Setting up Unicorn HAT:"
    unicornhat.brightness(config.BRIGHTNESS)
    unicornhat.rotation(config.ROTATION)
    print "   done."

def render_events(events, user=None):
    """
    Renders an iterable of events to the Unicorn HAT display.
    Takes the first 64 events from the iterable and renders them
    in right-to-left, bottom-to-top order starting at the bottom-right pixel.
    Assuming the default GitHub API ordering, this puts the oldest event at the
    top-left and the newest bottom-right.
    """
    print "Rendering events:"
    count = ROWS*COLS
    eventpixels = (EventPixel(e, user) for e in islice(events, count))
    for i, eventpixel in enumerate(eventpixels):
        x = COLS - (i % COLS) - 1
        y = ROWS - (i // ROWS) - 1
        unicornhat.set_pixel(x, y, *eventpixel.rgb)
    unicornhat.show()
    print "   done."

def github_login():
    """Logs into GitHub API with the token from config.yml and returns a User object."""
    print "Github API login:"
    gh = login(token=config.GITHUB_TOKEN)
    user = gh.user()
    print "   done."
    return user

def main():
    load_config()
    setup_unicorn()
    user = github_login()

    events = user.iter_org_events(config.GITHUB_ORG)
    while True:
        render_events(events, user=user)
        events.refresh(True)
        time.sleep(config.REFRESH_SECONDS)

class AttrDict(dict):
    """A dict subclass that allows keys to be access as attributes"""
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self

if __name__ == '__main__':
    main()
