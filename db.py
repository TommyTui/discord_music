from peewee import SqliteDatabase, Model, CharField, IntegerField, fn

db = SqliteDatabase('discord.db')


class Music(Model):
    url = CharField()
    type = CharField()
    pid = IntegerField(null=True)

    class Meta:
        database = db
        indexes = (
            (('url', 'pid'), True),
        )


db.connect()
db.create_tables([Music])


def random_music(count=None):
    if count is None:
        return Music.select().order_by(fn.Random())
    else:
        return Music.select().order_by(fn.Random()).limit(count)


def insert(url, type, pid=None):
    Music.create(url=url, type=type, pid=pid)


def delete(url, pid=None):
    Music.delete().where(Music.url == url, Music.pid == pid).execute()


def list_all():
    return Music.select()
