"""TypesenseHelper
Wrapper on top of the Typesense API client"""

import json
import os
from builtins import range

import typesense
from typesense import exceptions
from typesense.aliases import Aliases
from typesense.api_call import ApiCall
from typesense.collections import Collections
from typesense.configuration import Node
from typesense.debug import Debug
from typesense.keys import Keys
from typesense.multi_search import MultiSearch
from typesense.operations import Operations


class CustomNode(Node):

    def url(self):
        return '{0}://{1}:8108{2}'.format(self.protocol, self.host, self.path)


class TypesenseHelper:
    """TypesenseHelper"""

    def __init__(self, alias_name, collection_name_tmp, custom_settings):

        self.typesense_client = typesense.Client({
            'api_key': os.environ.get('TYPESENSE_API_KEY', None),
            'nodes': [{
                'host': os.environ.get('TYPESENSE_HOST', None),
                'port': os.environ.get('TYPESENSE_PORT', None),
                'path': os.environ.get('TYPESENSE_PATH', ''),
                'protocol': os.environ.get('TYPESENSE_PROTOCOL', None)
            }]
        })

        # Patch the client to use the custom node that doesn't require port in the url. We then need to reinitialize
        # all the other classes on the client with the new configuration.
        node = self.typesense_client.config.nodes[0]
        self.typesense_client.config.nodes[0] = CustomNode(node.host, node.port, node.path, node.protocol)
        self.typesense_client.api_call = ApiCall(self.typesense_client.config)
        self.typesense_client.collections = Collections(self.typesense_client.api_call)
        self.typesense_client.multi_search = MultiSearch(self.typesense_client.api_call)
        self.typesense_client.keys = Keys(self.typesense_client.api_call)
        self.typesense_client.aliases = Aliases(self.typesense_client.api_call)
        self.typesense_client.operations = Operations(self.typesense_client.api_call)
        self.typesense_client.debug = Debug(self.typesense_client.api_call)

        self.alias_name = alias_name
        self.collection_name_tmp = collection_name_tmp
        self.collection_locale = os.environ.get('TYPESENSE_COLLECTION_LOCALE', 'en')
        self.custom_settings = custom_settings

    def create_tmp_collection(self):
        """Create a temporary index to add records to"""
        try:
            self.typesense_client.collections[self.collection_name_tmp].delete()
        except exceptions.ObjectNotFound:
            pass

        schema = {
            'name': self.collection_name_tmp,
            'fields': [
                {'name': 'anchor', 'type': 'string', 'optional': True},
                {'name': 'content', 'type': 'string', 'locale': self.collection_locale, 'optional': True},
                {'name': 'url', 'type': 'string', 'facet': True},
                {'name': 'url_without_anchor', 'type': 'string', 'facet': True, 'optional': True},
                {'name': 'version', 'type': 'string[]', 'facet': True, 'optional': True},
                {'name': 'hierarchy.lvl0', 'type': 'string', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': 'hierarchy.lvl1', 'type': 'string', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': 'hierarchy.lvl2', 'type': 'string', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': 'hierarchy.lvl3', 'type': 'string', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': 'hierarchy.lvl4', 'type': 'string', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': 'hierarchy.lvl5', 'type': 'string', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': 'hierarchy.lvl6', 'type': 'string', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': 'type', 'type': 'string', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': '.*_tag', 'type': 'string', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': 'language', 'type': 'string', 'facet': True, 'optional': True},
                {'name': 'tags', 'type': 'string[]', 'facet': True, 'locale': self.collection_locale, 'optional': True},
                {'name': 'item_priority', 'type': 'int64'},
            ],
            'default_sorting_field': 'item_priority',
            'token_separators': ['_', '-']
        }

        if self.custom_settings is not None:
            token_separators = self.custom_settings.get('token_separators', None)
            if token_separators is not None:
                schema['token_separators'] = token_separators

            symbols_to_index = self.custom_settings.get('symbols_to_index', None)
            if symbols_to_index is not None:
                schema['symbols_to_index'] = symbols_to_index

        self.typesense_client.collections.create(schema)

    def add_records(self, records, url, from_sitemap):
        """Add new records to the temporary index"""
        transformed_records = list(map(TypesenseHelper.transform_record, records))
        record_count = len(transformed_records)

        for i in range(0, record_count, 50):
            result = self.typesense_client.collections[self.collection_name_tmp].documents.import_(
                transformed_records[i:i + 50])
            failed_items = list(
                map(lambda r: json.loads(json.loads(r)),
                    filter(lambda r: json.loads(json.loads(r))['success'] is False, result)))
            if len(failed_items) > 0:
                print(failed_items)
                raise Exception

        color = "96" if from_sitemap else "94"

        print(
            '\033[{}m> DocSearch: \033[0m{}\033[93m {} records\033[0m)'.format(
                color, url, record_count))

    def commit_tmp_collection(self):
        """Update alias to point to new collection"""
        old_collection_name = None

        try:
            old_collection_name = self.typesense_client.aliases[self.alias_name].retrieve()['collection_name']
        except exceptions.ObjectNotFound:
            pass

        self.typesense_client.aliases.upsert(self.alias_name, {'collection_name': self.collection_name_tmp})

        if old_collection_name:
            self.typesense_client.collections[old_collection_name].delete()

    @staticmethod
    def transform_record(record):
        transformed_record = {k: v for k, v in record.items() if v is not None}

        # Deprioritize wrapper links from the results and promote content matches and the actual page we're on to the top
        split_url = transformed_record.get('url_without_anchor', '').replace('http://', '').split('/')

        depth_rank = 10
        for idx, url_part in enumerate(split_url):
            if url_part in str(record.get('content', '')).lower().replace(' ', '_') or url_part in str(record.get('content', '')).lower().replace(' ', '-'):
                if idx == len(split_url) - 1:
                    depth_rank = 20
                else:
                    depth_rank = 0

        # Promote introduction pages for topics and demote changelogs and migration guides
        transformed_record['item_priority'] = 0 + \
            int('Introduction' in transformed_record.get('content', '')) * 30 + \
            transformed_record.get('weight', {}).get('level', 0) / 5 + \
            (-50 if 'changelog' in transformed_record.get('url', '') else 0) + \
            (-20 if 'migration_guides' in transformed_record.get('url', '') else 0) + \
            depth_rank

        # Flatten nested hierarchy field
        for x in range(0, 7):
            if record['hierarchy'][f'lvl{x}'] is None:
                continue
            transformed_record[f'hierarchy.lvl{x}'] = record['hierarchy'][f'lvl{x}']

        # Convert version to array
        if 'version' in record and type(record['version']) == str:
            transformed_record['version'] = record['version'].split(',')

        return transformed_record
