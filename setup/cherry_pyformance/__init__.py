import json
import os.path
import sys
import time
import logging
import copy
from urllib2 import urlopen, Request
from shutil import copyfile
import cherrypy
from cherrypy.process.plugins import Monitor



# initialise 3 buffers
function_stats_buffer = {}
sql_stats_buffer = {}


stat_logger = None
cfg = None
push_stats = None
stats_package_template = None

def get_stat(item, stat):
    """
    Returns the value of an item's stat based on the stat name, not the tuple index
    """
    f = ('file','line','name')
    s = ('native_calls','total_calls','time','cumulative')
    if stat in f:
        return item[0][f.index(stat)]
    elif stat in s:
        return item[1][s.index(stat)]
    else:
        return 0


def create_output_fn():
    """
    Creates an output function for dealing with the stats_buffer on flush.
    Uses the configuration to determine the method (write or POST) and
    location to push the data to and constructs a function based on this.
    """
    try:
        output_type = cfg['output']['type']
        location = str(cfg['output']['location'])
        compress = cfg['output']['compress']
        if output_type == 'disk':
            stat_logger.info('Writing collected stats to %s' % location)
            if compress:
                import gzip
                def push_stats_fn(stats, location=location):
                    """A function to write the compressed json to disk"""
                    print stats['type']
                    filename = os.path.join(location, 'tms_%s_stats_%s.json.gz'%( stats['type'], str(int(time.time())) ) )
                    f = gzip.open(filename,'wb')
                    f.write(json.dumps(stats, indent=4, separators=(',', ': ')))
                    f.close()

            else:
                def push_stats_fn(stats, location=location):
                    """A function to write the json to disk"""
                    filename = os.path.join(location, 'tms_%s_stats_%s.json'%( stats['type'], str(int(time.time())) ) )
                    with open(filename,'w') as json_file:
                        json.dump(stats, json_file, indent=4, separators=(',', ': '))

        elif output_type == 'server':
            if compress:
                import zlib
            address = location if location.startswith('http://') else 'http://'+location
            stat_logger.info('Sending collected stats to %s' % address)

            def push_stats_fn(stats, location=location):
                """A function to push json to server"""
                output = json.dumps(stats, indent=4, separators=(',', ': '))
                if compress:
                    output = zlib.compress(output)
                ############# TODO MAKE THIS HTTPS
                urlopen(Request('%s/%s'%(address,stats['type']), output, headers={'Content-Type':'application/json'}))

        else:
            # if no valid method found, raise a KeyError to be caught
            stat_logger.warning('Invalid stats output param given, use "disk" or "server"')
            raise KeyError
    except KeyError:
        # could not ascertain output method, do nothing with stats
        stat_logger.info('Could not ascertain output method, defaulting to "pass". Check the profile_stats_config.json is valid.')
        def push_stats_fn(stats):
            pass
    return push_stats_fn


def load_config(config_file_path):
    try:
        with open(config_file_path) as cfg_file:
            cfg = json.load(cfg_file)
            return cfg
    except:
        try:
            stat_logger.info('Failed to load stats profiling configuration. Creating from default.')
            default_config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "default_config.json")
            copyfile(default_config_file, config_file_path)
            with open(config_file_path) as cfg_file:
                cfg = json.load(cfg_file)
            return cfg
        except:
            stat_logger.error('Failed to create config file from default')
            sys.exit(1)

def setup_logging():
    '''
    Sets up the stats logger.
    '''
    stat_logger = logging.getLogger('stats')
    stats_log_handler = logging.Handler(level='INFO')
    log_format = '%(asctime)s::%(levelname)s::[%(module)s:%(lineno)d]::[%(threadName)s] %(message)s'
    stats_log_handler.setFormatter(log_format)
    stat_logger.addHandler(stats_log_handler)
    return stat_logger


def flush_function_stats():
    """
    If there are items on the function_stats_buffer, their stats tuples are
    parsed to a dictionary and the records are pushed to whichever output
    is configured in the config file. (Currently json dump or push to server)
    """
    global function_stats_buffer
    stat_logger.info('Flushing function stats buffer.')
    # initialise a package of stats to push, not all stats may be ready to be pushed
    stats_to_push = []
    for _id in function_stats_buffer.keys():
        # test if there is a pstats key
        if 'pstats' in function_stats_buffer[_id]:
            pstats_buffer = function_stats_buffer[_id]['pstats']
            parsed_stats = []
            # convert all stats tuples to dictionaries
            for stat in pstats_buffer:
                parsed_stats.append({'function':{'module':stat[0][0],
                                                 'line':stat[0][1],
                                                 'name':stat[0][2]},
                                     'native_calls':stat[1][0],
                                     'total_calls':stat[1][1],
                                     'time':stat[1][2],
                                     'cumulative':stat[1][3] })
            function_stats_buffer[_id]['pstats'] = parsed_stats
            # put a deep copy on the stats_to_push list
            stats_to_push.append(copy.deepcopy(function_stats_buffer[_id]))
            # remove parsed stats, keeping transient stats
            del function_stats_buffer[_id]
    length = len(stats_to_push)
    if length != 0:
        stats_package = copy.deepcopy(stats_package_template)
        stats_package['stats'] = stats_to_push
        print 'func'
        stats_package['type'] = 'func'
        push_stats(stats_package)
        stat_logger.info('Flushed %d stats from the function buffer' % length)
    else:
        stat_logger.info('No stats on the function buffer to flush.')

def flush_sql_stats():
    """
    If there are items on the sql_stats_buffer, they are pushed to whichever output
    is configured in the config file. (Currently json dump or push to server)
    """
    global sql_stats_buffer
    stat_logger.info('Flushing SQL stats buffer.')
    # initialise a package of stats to push, not all stats may be ready to be pushed
    stats_to_push = []
    for _id in sql_stats_buffer.keys():
        stats_to_push.append(copy.deepcopy(sql_stats_buffer[_id]))
        del sql_stats_buffer[_id]
    length = len(stats_to_push)
    if length != 0:
        stats_package = copy.deepcopy(stats_package_template)
        stats_package['stats'] = stats_to_push
        stats_package['type'] = 'sql'
        print 'sql'
        push_stats(stats_package)
        stat_logger.info('Flushed %d stats from the SQL buffer' % length)
    else:
        stat_logger.info('No stats on the SQL buffer to flush.')

def flush_stats():
    if cfg['handlers'] or cfg['functions']:
        flush_function_stats()
    if cfg['database']:
        flush_sql_stats()


def initialise(config_file_path):
    global cfg
    cfg = load_config(config_file_path)

    global stat_logger
    stat_logger = setup_logging()
    
    global push_stats
    push_stats = create_output_fn()
    
    global stats_package_template
    stats_package_template = {'exhibitor_chain': cfg['exhibitor_chain'],
                              'exhibitor_branch': cfg['exhibitor_branch'],
                              'product': cfg['product'],
                              'version': cfg['version'],
                              'stats': []}

    if cfg['functions']:
        from function_profiler import decorate_functions
        cherrypy.engine.subscribe('start', decorate_functions, 0)
    if cfg['handlers']:
        from handler_profiler import decorate_handlers
        cherrypy.engine.subscribe('start', decorate_handlers, 0)
    if cfg['database']:
        from sql_profiler import decorate_connections
        cherrypy.engine.subscribe('start', decorate_connections, 0)


    # create a monitor to periodically flush the stats buffers at the flush_interval
    Monitor(cherrypy.engine, flush_stats,
        frequency=cfg['flush_interval'],
        name='Flush stats buffers').subscribe()

    # when the engine stops, flush any stats.
    cherrypy.engine.subscribe('stop', flush_stats)
