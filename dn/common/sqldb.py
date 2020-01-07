from dn.common import log

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

try:
    from greenlet import getcurrent as get_ident
except ImportError:
    try:
        from thread import get_ident
    except ImportError:
        from _thread import get_ident

BaseModel = declarative_base()

dbsession_cache = {}
dbsession_used = {}

logger = log.get_logger('rock.sqldb')


def create_sqldb_engine(url, options={}):
    kwargs = {'pool_size': 20, 'max_overflow': 0, 'pool_recycle': 3600}
    kwargs.update(options or {})
    return create_engine(url, **kwargs)


def update_dbsession_used(name):
    ident = get_ident()
    used = dbsession_used.setdefault(ident, set())
    used.add(name)


def get_dbsession(name='default'):
    from .globals import config
    if name not in dbsession_cache:
        conf = config.sqldb.get(name, {})
        engine = create_sqldb_engine(conf['url'], conf.get('options', {}))
        dbsession = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=engine))
        dbsession_cache[name] = dbsession
    dbsession_class = dbsession_cache[name]
    update_dbsession_used(name)
    dbsession_class()
    return dbsession_class


def clear_dbsession():
    global dbsession_used
    ident = get_ident()
    dbsessions = dbsession_used.pop(ident, [])
    for name in dbsessions:
        try:
            dbsession_class = dbsession_cache.get(name)
            dbsession_class.remove()
        except Exception:
            logger.error('error while clear dbsession')
            logger.traceback()
