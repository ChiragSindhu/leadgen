"""Route modules, one blueprint per feature area."""


def register(app):
    from . import auth, leads, find, runs, send, media, whatsapp, settings, agent
    for m in (auth, leads, find, runs, send, media, whatsapp, settings, agent):
        app.register_blueprint(m.bp)
