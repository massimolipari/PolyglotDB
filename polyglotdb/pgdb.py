#!/usr/bin/env python

import os
import sys
import argparse
import shutil
import configparser
import subprocess
import signal
from urllib.request import urlretrieve
from tqdm import tqdm


def load_config():
    c = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        c.read(CONFIG_PATH)
    else:
        c['Neo4j'] = {'http_port': 7474,
                      'https_port': 7475,
                      'bolt_port': 7687
                      }
        c['Neo4j_wrapper'] = {'max_heap': 4096}
        c['InfluxDB'] = {'http_port': 8086,
                         'udp_port': 8087,
                         'auth_enabled': 'false',
                         'data_directory': os.path.join(DEFAULT_DATA_DIR, 'influxdb', 'data'),
                         'wal_directory': os.path.join(DEFAULT_DATA_DIR, 'influxdb', 'wal'),
                         'meta_directory': os.path.join(DEFAULT_DATA_DIR, 'influxdb', 'meta')}
        c['Data'] = {'directory': DEFAULT_DATA_DIR}
        global CONFIG_CHANGED
        CONFIG_CHANGED = True
    return c


def save_config(c):
    with open(CONFIG_PATH, 'w') as configfile:
        c.write(configfile)


NEO4J_VERSION = '5.21.0'

INFLUXDB_VERSION = '1.8.9'


def tqdm_hook(t):
    last_b = [0]

    def inner(b=1, bsize=1, tsize=None):
        if tsize is not None:
            t.total = tsize
        t.update((b - last_b[0]) * bsize)
        last_b[0] = b

    return inner


def download_neo4j(data_directory, overwrite=False):
    neo4j_directory = os.path.join(data_directory, 'neo4j')
    if not overwrite and os.path.exists(neo4j_directory):
        print('Using existing Neo4j installation.')
        return
    os.makedirs(TEMP_DIR, exist_ok=True)
    print('Downloading Neo4j...')

    if sys.platform.startswith('win'):
        dist_string = 'windows.zip'
        path = os.path.join(TEMP_DIR, 'neo4j.zip')
    else:
        dist_string = 'unix.tar.gz'
        path = os.path.join(TEMP_DIR, 'neo4j.tar.gz')

    download_link = 'https://neo4j.com/artifact.php?name=neo4j-community-{version}-{dist_string}'.format(
        version=NEO4J_VERSION, dist_string=dist_string)

    with tqdm(unit='B', unit_scale=True, miniters=1) as t:
        filename, headers = urlretrieve(download_link, path, reporthook=tqdm_hook(t), data=None)
    shutil.unpack_archive(filename, data_directory)
    for d in os.listdir(data_directory):
        if d.startswith(('neo4j')):
            os.rename(os.path.join(data_directory, d), neo4j_directory)

    if sys.platform.startswith('win'):
        import win32com.shell.shell as shell
        exe = 'neo4j.bat'
        neo4j_bin = os.path.join(CONFIG['Data']['directory'], 'neo4j', 'bin', exe)
        params = 'windows-service install'
        shell.ShellExecuteEx(lpVerb='runas', lpFile=neo4j_bin, lpParameters=params)
    return True


def download_influxdb(data_directory, overwrite=False):
    influxdb_directory = os.path.join(data_directory, 'influxdb')
    if not overwrite and os.path.exists(influxdb_directory):
        print('Using existing InfluxDB installation.')
        return
    os.makedirs(TEMP_DIR, exist_ok=True)
    print('Downloading InfluxDB...')

    if sys.platform.startswith('win'):
        dist_string = 'windows_amd64.zip'
        path = os.path.join(TEMP_DIR, 'influxdb.zip')
    elif sys.platform == 'darwin':
        dist_string = 'darwin_amd64.tar.gz'
        path = os.path.join(TEMP_DIR, 'influxdb.tar.gz')
    else:
        dist_string = 'linux_amd64.tar.gz'
        path = os.path.join(TEMP_DIR, 'influxdb.tar.gz')

    download_link = 'https://dl.influxdata.com/influxdb/releases/influxdb-{version}_{dist_string}'.format(
        version=INFLUXDB_VERSION, dist_string=dist_string)

    with tqdm(unit='B', unit_scale=True, miniters=1) as t:
        filename, headers = urlretrieve(download_link, path, reporthook=tqdm_hook(t), data=None)
    shutil.unpack_archive(filename, data_directory)
    for d in os.listdir(data_directory):
        if d.startswith(('influxdb')):
            os.rename(os.path.join(data_directory, d), influxdb_directory)

    return True


    
def configure_neo4j(data_directory):
    from polyglotdb.databases.config import neo4j_template_path
    neo4j_conf_path = os.path.join(data_directory, 'neo4j', 'conf', 'neo4j.conf')
    with open(neo4j_template_path, 'r') as f:
        template = f.read()

    with open(neo4j_conf_path, 'w') as f:
        f.write(template.format(**CONFIG['Neo4j']))


def make_influxdb_safe(string):
    if not isinstance(string, str):
        return string
    return string.replace("\\", "/")


def configure_influxdb(data_directory):
    from polyglotdb.databases.config import influxdb_template_path
    os.makedirs(os.path.join(data_directory, 'influxdb'), exist_ok=True)
    influxdb_conf_path = os.path.join(data_directory, 'influxdb', 'influxdb.conf')

    with open(influxdb_template_path, 'r') as f:
        template = f.read()

    with open(influxdb_conf_path, 'w') as f:
        f.write(template.format(**{k: make_influxdb_safe(v) for k, v in CONFIG['InfluxDB'].items()}))


def display_help():
    pass


def uninstall():
    directory = CONFIG['Data']['directory']
    if not os.path.exists(directory):
        print('Could not uninstall, data directory does not exist.')

    if sys.platform.startswith('win'):
        import win32com.shell.shell as shell
        exe = 'neo4j.bat'
        neo4j_bin = os.path.join(CONFIG['Data']['directory'], 'neo4j', 'bin', exe)
        params = 'windows-service uninstall'
        shell.ShellExecuteEx(lpVerb='runas', lpFile=neo4j_bin, lpParameters=params)

    try:
        shutil.rmtree(directory)
        shutil.rmtree(CONFIG_DIR)
    except FileNotFoundError:
        pass


def start():
    try:
        shutil.rmtree(os.path.expanduser('~/.neo4j'))
    except FileNotFoundError:
        pass
    if sys.platform.startswith('win'):
        exe = 'neo4j.bat'
    else:
        exe = 'neo4j'

    neo4j_bin = os.path.join(CONFIG['Data']['directory'], 'neo4j', 'bin', exe)
    print(neo4j_bin)
    subprocess.call([neo4j_bin, 'start'])
    print(neo4j_bin)
    if sys.platform.startswith('win'):
        influxdb_bin = os.path.join(CONFIG['Data']['directory'], 'influxdb', 'influxd.exe')
    else:
        influxdb_bin = os.path.join(CONFIG['Data']['directory'], 'influxdb', 'usr', 'bin', 'influxd')
    influxdb_conf = os.path.join(CONFIG['Data']['directory'], 'influxdb', 'influxdb.conf')
    influx_proc = subprocess.Popen([influxdb_bin, '-config', influxdb_conf],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,
                                   stdin=subprocess.DEVNULL,
                                   restore_signals=False,
                                   start_new_session=True)
    pid_file = os.path.join(CONFIG_DIR, 'influxd.pid')
    with open(pid_file, 'w') as f:
        f.write(str(influx_proc.pid))


def stop():
    if sys.platform.startswith('win'):
        exe = 'neo4j.bat'
    else:
        exe = 'neo4j'
    neo4j_bin = os.path.join(CONFIG['Data']['directory'], 'neo4j', 'bin', exe)
    subprocess.call([neo4j_bin, 'stop'])
    pid_file = os.path.join(CONFIG_DIR, 'influxd.pid')
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        os.remove(pid_file)
    except FileNotFoundError:
        pass


def status(name):
    pass


def main():
    global CONFIG_DIR
    CONFIG_DIR = os.environ.get('PGDB_HOME', os.path.expanduser('~/.pgdb'))

    global DEFAULT_DATA_DIR
    DEFAULT_DATA_DIR = os.path.join(CONFIG_DIR, 'data')

    global CONFIG_PATH
    CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.ini')

    global CONFIG_CHANGED
    CONFIG_CHANGED = False

    global CONFIG
    CONFIG = load_config()

    global TEMP_DIR
    TEMP_DIR = os.path.join(CONFIG_DIR, 'downloads')


    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(help='Command to use')
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument('directory', nargs='?', help='Path to install data', default='')
    install_parser.add_argument('-q', '--quiet', help="Suppress user input", action='store_true')
    install_parser.add_argument('-d', '--download', help="Force download of new versions", action='store_true')
    install_parser.set_defaults(which='install')

    start_parser = subparsers.add_parser("start")
    start_parser.set_defaults(which='start')

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(which='status')

    stop_parser = subparsers.add_parser("stop")
    stop_parser.set_defaults(which='stop')

    remove_parser = subparsers.add_parser("uninstall")
    remove_parser.set_defaults(which='uninstall')

    args = parser.parse_args()
    if not hasattr(args, 'which') or args.which == 'help':
        parser.print_usage()
        return
    elif args.which == 'install':
        directory = os.path.expanduser(args.directory)
        if not directory:
            directory = DEFAULT_DATA_DIR
            if not args.quiet:
                user_input = input(
                    'No install directory was specified, so required files will be installed to {}. Is that okay? (Y/N)'.format(
                        directory))
                if user_input.lower() != 'y':
                    sys.exit(1)
        else:
            CONFIG['Data']['directory'] = directory
            CONFIG['InfluxDB']['data_directory'] = os.path.join(directory, 'influxdb', 'data')
            CONFIG['InfluxDB']['wal_directory'] = os.path.join(directory, 'influxdb', 'wal')
            CONFIG['InfluxDB']['meta_directory'] = os.path.join(directory, 'influxdb', 'meta')
            CONFIG_CHANGED = True
        if os.path.exists(directory):
            if args.quiet:
                uninstall()
            else:
                check = input('The current directory already exists, would you like to overwrite it? (Y/N)').lower()
                if check == 'y':
                    uninstall()
                else:
                    print('Aborting installation.')
                    sys.exit()
        download_neo4j(directory, overwrite=args.download)
        configure_neo4j(directory)
        download_influxdb(directory, overwrite=args.download)
        configure_influxdb(directory)
        try:
            shutil.rmtree(TEMP_DIR)
        except FileNotFoundError:
            pass
    elif args.which == 'uninstall':
        uninstall()
    elif args.which == 'start':
        start()
    elif args.which == 'status':
        pass
    elif args.which == 'stop':
        stop()

    if CONFIG_CHANGED:
        save_config(CONFIG)

if __name__ == '__main__':
    main()
