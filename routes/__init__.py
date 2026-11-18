"""Route modules, one blueprint per feature area."""


def register(app):
    from . import auth, leads, find, runs, send, media, whatsapp, settings
    for m in (auth, leads, find, runs, send, media, whatsapp, settings):
        app.register_blueprint(m.bp)
