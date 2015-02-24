class AttrDict(dict):
    """A dict subclass that allows keys to be accessed as attributes"""
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self
