import copy

from tinydb import TinyDB, where
from tinydb.storages import MemoryStorage

from module.base.decorator import cached_property
from module.base.timer import timer
from module.config.utils import *
from module.logger import logger

CONFIG_IMPORT = '''
import datetime

from module.config.argument import Argument

# This file was automatically generated by module/config/db.py.
# Don't modify it manually.


class GeneratedConfig:
    """
    Auto generated configuration
    """
'''.strip().split('\n')


class ManualStorage(MemoryStorage):
    """
    A poor implement to improve performance of TinyDB.

    Use `load()` and `save()` to read/write file,
    while TinyDB uses `read()` and `write()`, which are in memory.
    """

    def load(self):
        if self.memory:
            return self.memory
        else:
            self.memory = read_file(filepath_db())
            return self.memory

    def save(self):
        write_file(filepath_db(), self.memory)


def parse_value(value, data):
    """
    Convert a string to float, int, datetime, if possible.

    Args:
        value (str):
        data (dict):

    Returns:

    """
    option = data['option']
    if option:
        if value not in option:
            return data['value']
    if isinstance(value, str):
        if value == '':
            return None
        if '.' in value:
            try:
                return float(value)
            except ValueError:
                pass
        else:
            try:
                return int(value)
            except ValueError:
                pass
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass

    return value


def request_to_query(request):
    """
    Converts a request in dict to TinyDB query conditions.

    Args:
        request (dict):

    Returns:

    """
    func = request.get('func', None)
    group = request.get('group', None)
    arg = request.get('arg', None)
    lang = request.get('lang', None)

    query = None
    if func:
        query = where('func') == func if query is None else query & (where('func') == func)
    if group:
        query = where('group') == group if query is None else query & (where('group') == group)
    if arg:
        query = where('arg') == arg if query is None else query & (where('arg') == arg)
    if lang:
        query = where('lang') == lang if query is None else query & (where('lang') == lang)

    return query


def data_to_path(data):
    """
    Args:
        data (dict):

    Returns:
        str: <func>.<group>.<arg>
    """
    return '.'.join([data.get(attr, '') for attr in ['func', 'group', 'arg']])


class Database:
    # lang = ['zh-CN', 'en-US', 'zh-TW']
    lang = ['zh-CN']

    def __init__(self):
        self._config = {}
        self._config_updated = set()

    @cached_property
    def db(self):
        """
        Get database.
        """
        db = TinyDB(storage=ManualStorage)
        db.storage.load()
        return db

    def config(self, config_name):
        """
        Get config from given name.

        Args:
            config_name (str):

        Returns:
            dict:
        """
        if config_name in self._config:
            return self._config[config_name]
        elif config_name in self._config_updated:
            data = read_file(filepath_config(config_name))
            self._config[config_name] = data
            return data
        else:
            data = self.update_config(config_name)
            self._config_updated.add(config_name)
            self._config[config_name] = data
            return data

    def config_save(self, config_name):
        write_file(filepath_config(config_name), data=self.config(config_name))

    def config_clear(self, config_name):
        if isinstance(config_name, dict):
            config_name = config_name.get('config', None)
        if config_name:
            self._config.pop(config_name, None)

    def update_db(self):
        """
        Update args.yaml to args_db.yaml, also template.yaml
        """
        logger.info('Updating arguments database')
        old = self.db
        new = TinyDB(storage=ManualStorage)
        data = read_file(filepath_arg())

        for data in self._data_iter(data):
            res = old.search((where('func') == data['func'])
                             & (where('group') == data['group'])
                             & (where('arg') == data['arg'])
                             & (where('lang') == data['lang']))
            res = res[0] if len(res) else {}
            res = self._data_merge(old=res, args=data)
            new.insert(res)

        new.storage.save()
        self.update_config('template')
        del self.__dict__['db']

    def update_code(self):
        logger.info('Updating generated code')
        visited_path = set()
        visited_func = set()
        lines = CONFIG_IMPORT
        args = self.db.search(request_to_query({'lang': 'zh-CN'}))
        for arg in args:
            if arg['func'] not in visited_func:
                lines.append('')
                lines.append(f'    # Func `{arg["func"]}`')
                visited_func.add(arg['func'])
            path = f'{arg["group"]}.{arg["arg"]}'
            if path in visited_path or '_info' in path:
                continue
            data = {'value': parse_value(arg["value"], data=arg), 'path': path}
            if arg['option']:
                data['option'] = tuple(list(arg['option'].keys()))
            lines.append(f'    {path_to_arg(path)} = Argument({dict_to_kv(data)})')
            visited_path.add(path)

        with open(filepath_code(), 'w') as f:
            for text in lines:
                f.write(text + '\n')

    def _data_iter(self, args):
        visited = set()

        def info(raw):
            out = []
            for replace in [None, 'arg', 'group']:
                if replace:
                    raw[replace] = '_info'
                key = (raw['func'], raw['group'], raw['arg'], raw['lang'])
                if key not in visited:
                    visited.add(key)
                    out.append(copy.copy(raw))
            return reversed(out)

        for func, func_data in args.items():
            for group, group_data in func_data.items():
                for arg, value in group_data.items():
                    for lang in self.lang:
                        data = {
                            'func': func,
                            'group': group,
                            'arg': arg,
                            'lang': lang,
                            'value': value,
                        }
                        if isinstance(value, dict):
                            data.update(value)
                        for row in info(data):
                            yield row

    def _data_merge(self, old, args):
        """
        Args:
            old: An old row in args_db.yaml
            args: A row in args.yaml

        Returns:
            dict: Updated row to insert to args_db.yaml
        """
        data = {
            'func': '',
            'group': '',
            'arg': '',
            'lang': '',
            'name': '',
            'help': '',
            'type': 'input',
            'value': '',
            'option': {},
        }
        data.update(args)
        # From old row
        key = data_to_path(data)
        for attr in ['name', 'help']:
            v = old.get(attr, '')
            v = v if v else f'{key}.{attr}'
            data[attr] = v
        # Update option
        option = data['option']
        if option:
            data['option'] = {k: deep_get(old, f'option.{k}', default=k) for k in option}
        # Remove redundant attributes in _info
        if data['arg'] == '_info':
            data.update({
                'type': '',
                'value': '',
                'option': {},
            })
        return data

    @timer
    def update_config(self, config_name):
        """
        Args:
            config_name (str):
        """
        file = filepath_config(config_name)
        logger.info(f'Updating user config: {file}')
        old = read_file(file)
        new = {}
        arguments = self.db.search(where('lang') == 'zh-CN')
        for arg in arguments:
            if arg['group'] == '_info' or arg['arg'] == '_info':
                continue
            path = data_to_path(arg)
            value = deep_get(old, keys=path, default=arg['value'])
            value = parse_value(value, data=arg)
            deep_set(new, keys=path, value=value)

        new = self._check_config(new, is_template=config_name == 'template')
        write_file(file, data=new)
        return new

    def _check_config(self, data, is_template=False):
        """
        Check a user config

        Args:
            data (dict):
            is_template (bool):

        Returns:
            dict:
        """
        if is_template:
            deep_set(data, 'Alas.DropRecord.AzurStatsID', None)
        else:
            deep_default(data, 'Alas.DropRecord.AzurStatsID', random_id())

        return data

    def select_db(self, request):
        """
        Args:
            request (dict): Such as {"config": "alas", "func": "Main", "group": "Scheduler"}

        Returns:
            dict:
        """
        func = request.get('func', None)
        group = request.get('group', None)
        arg = request.get('arg', None)

        assert func or group or arg, 'Must fill one of `func`, `group` or `arg` in request'

        result = self.db.search(request_to_query(request))

        response = {}
        for arg in result:
            deep_set(response, keys=data_to_path(arg), value=arg)
        return response

    def select_config(self, request):
        """
        Args:
            request (dict): Such as {"config": "alas", "func": "Main", "group": "Scheduler"}

        Returns:
            dict:
        """
        func = request.get('func', None)
        group = request.get('group', None)
        arg = request.get('arg', None)
        config = request.get('config', None)
        assert func, 'Must fill `func` in request'
        assert config, 'Must fill `config` in request'
        if group:
            assert func, 'Must fill `func` in request, if `group filled`'
        if arg:
            assert func, 'Must fill `group` in request, if `arg filled`'

        response = self.select_db(request)
        path = '.'.join([attr for attr in [func, group, arg] if attr])
        value = deep_get(self.config(config), keys=path)
        deep_set(response, keys=path, value=value)

        return response

    def select_function(self, request):
        func = request.get('func', None)
        lang = request.get('lang', None)
        config = request.get('config', None)
        assert func, 'Must fill `func` in request'
        assert lang, 'Must fill `lang` in request'
        assert config, 'Must fill `config` in request'

        request = {'func': func, 'lang': lang, 'config': config}
        database = self.select_db(request)
        config = self.select_config(request)

        for func, func_data in config.items():
            for group, group_data in func_data.items():
                for arg, value in group_data.items():
                    path = f'{func}.{group}.{arg}.value'
                    if value is not None:
                        deep_set(database, keys=path, value=value)

        return database

    def upsert_config(self, request):
        """
        Args:
            request:

        Returns:

        """
        func = request.get('func', None)
        group = request.get('group', None)
        arg = request.get('arg', None)
        lang = request.get('lang', None)
        value = request.get('value', None)
        config = request.get('config', None)
        assert func and group and arg and lang, 'Must fill all of `func`, `group`,  `arg` and `lang` in request'
        assert value is not None, 'Must fill `value` in request'
        assert config, 'Must fill `config` in request'

        path = data_to_path(request)
        default = deep_get(self.select_db(request), keys=path)
        value = parse_value(value, data=default)
        if value is None:
            value = default['value']
        deep_set(self.config(config), keys=path, value=value)

        response = self.select_function({'func': func, 'lang': lang, 'config': config})
        write_file(filepath_config(config), data=self.config(config))
        return response

    def upsert_db(self, request):
        func = request.get('func', None)
        group = request.get('group', None)
        arg = request.get('arg', None)
        lang = request.get('lang', None)
        config = request.get('config', None)
        assert func and group and arg and lang, 'Must fill all of `func`, `group`,  `arg` and `lang` in request'

        self.db.update(request, request_to_query(request))
        self.db.storage.save()
        response = self.select_function({'func': func, 'lang': lang, 'config': config})
        return response

    def select_menu(self, request):
        """
        Args:
            request:

        Returns:

        """
        lang = request.get('lang', None)
        assert lang, 'Must fill `lang` in request'

        response = self.select_db({'group': '_info', 'lang': lang})
        return response


if __name__ == '__main__':
    m = Database()
    m.update_db()
    m.update_code()

    # res = m.select_db({'func': 'Main', 'group': 'Scheduler'})
    # print(res)
    # res = m.select_config({"config": "alas", "func": "Alas", "group": "Scheduler"})
    # print(res)
    # res = m.select_function({"config": "alas", "lang": "zh-CN", "func": "Alas", "group": "Scheduler"})
    # print(res)
    # res = m.upsert_config({"config": "alas", "lang": "zh-CN", "func": "Alas", "group": "Scheduler", "arg": "FailureInterval", "value": '12222'})
    # print(res)

    # res = m.select_db({'group': '_info', 'lang': 'zh-CN'})
    # print(json.dumps(res, indent=2, ensure_ascii=True, sort_keys=False, default=str))


