# pyinfra
# File: pyinfra/api/inventory.py
# Desc: represents a pyinfra inventory

from collections import defaultdict

import six

from pyinfra import logger

from .connectors import (
    ALL_CONNECTORS,
    EXECUTION_CONNECTORS,
    INVENTORY_CONNECTORS,
)
from .exceptions import NoConnectorError, NoGroupError, NoHostError
from .host import Host
from .util import FallbackDict


def extract_name_data(names):
    for name in names:
        data = {}

        if isinstance(name, tuple):
            data = name[1]
            name = name[0]

        yield name, data


class Inventory(object):
    '''
    Represents a collection of target hosts. Stores and provides access to group data,
    host data and default data for these hosts.

    Args:
        names_data: tuple of ``(names, data)``
        ssh_user: override SSH user
        ssh_port: override SSH port
        ssh_key: override SSH key filename
        ssh_key_password: override password for the SSH key
        ssh_password: override SSH password
        **groups: map of group names -> ``(names, data)``
    '''

    state = None

    def __init__(
        self, names_data,
        ssh_user=None, ssh_port=None, ssh_key=None,
        ssh_key_password=None, ssh_password=None, **groups
    ):
        # Setup basics
        self.groups = defaultdict(list)  # lists of Host objects
        self.host_data = defaultdict(dict)  # dict of name -> data
        self.group_data = defaultdict(dict)  # dict of name -> data

        # In CLI mode these are --user, --key, etc
        override_data = {
            'ssh_user': ssh_user,
            'ssh_key': ssh_key,
            'ssh_key_password': ssh_key_password,
            'ssh_port': ssh_port,
            'ssh_password': ssh_password,
        }
        # Strip None values
        override_data = {
            key: value
            for key, value in six.iteritems(override_data)
            if value is not None
        }
        self.override_data = override_data

        names, data = names_data

        # Assign global data
        self.data = data

        # Create the actual host instances and groups
        self.hosts = self.make_hosts_and_groups(names, groups)

    def make_hosts_and_groups(self, names, groups):
        # Map name -> data
        name_to_data = defaultdict(dict)
        # Map name -> group names
        name_to_group_names = defaultdict(list)

        for group_name, (group_names, group_data) in six.iteritems(groups):
            # Assign group data
            self.group_data[group_name] = group_data

            # For any hosts in the group, assign mappings
            for name, data in extract_name_data(group_names):
                name_to_data[name].update(data)
                name_to_group_names[name].append(group_name)

        # Build all/top-level host data - *before* we expand any inventory
        # connectors.
        for name, data in extract_name_data(names):
            name_to_data[name].update(data)

        # Now, use the above to fill self.host_data and populate names_executors
        names_executors = []

        for name, _ in extract_name_data(names):
            host_data = name_to_data[name]

            # Default to executing commands with the ssh connector
            executor = EXECUTION_CONNECTORS['ssh']

            # Name is @connector?
            if name[0] == '@':
                connector_name = name[1:]
                arg_string = None

                if '/' in connector_name:
                    connector_name, arg_string = connector_name.split('/', 1)

                if connector_name not in ALL_CONNECTORS:
                    raise NoConnectorError(
                        'Invalid connector: {0}'.format(connector_name),
                    )

                # Execution connector? Simple, just set it for ther host
                if connector_name in EXECUTION_CONNECTORS:
                    executor = EXECUTION_CONNECTORS[connector_name]

                # Inventory connector?
                if connector_name in INVENTORY_CONNECTORS:
                    logger.debug('Expanding inventory connector: {0}'.format(
                        connector_name,
                    ))

                    for name, data, group_names in (
                        INVENTORY_CONNECTORS[connector_name].make_names_data(arg_string)
                    ):
                        # Make a copy of the host data, update with any from
                        # the connector.
                        sub_host_data = host_data.copy()
                        sub_host_data.update(data)

                        # Assign the name/data/group_names from the connector
                        self.host_data[name] = sub_host_data
                        names_executors.append((name, executor))
                        name_to_group_names[name].extend(group_names)

                    continue

            # Assign the name/data
            self.host_data[name] = host_data
            names_executors.append((name, executor))

        # Now we can actually make Host instances
        hosts = {}

        for name, executor in names_executors:
            host_groups = name_to_group_names[name]

            # Create the (waterfall data: override, host, group, global)
            host_data = FallbackDict(
                self.get_override_data(),
                self.get_host_data(name),
                self.get_groups_data(host_groups),
                self.get_data(),
                # Pass the method, rather than data, as this comes from the
                # state and can change during deploy(s).
                self.get_deploy_data,
            )

            # Create the Host object
            host = Host(
                name,
                inventory=self,
                groups=name_to_group_names.get(name),
                data=host_data,
                executor=executor,
            )
            hosts[name] = host

            # And push into any groups
            for group_name in host_groups:
                if host not in self.groups[group_name]:
                    self.groups[group_name].append(host)

        return hosts

    def __getitem__(self, key):
        '''
        DEPRECATED: please use ``Inventory.get_host`` instead.
        '''

        # COMPAT w/ <0.4
        # TODO: remove this function

        logger.warning((
            'Use of Inventory[<host_name>] is deprecated, '
            'please use `Inventory.get_host` instead.'
        ))

        if key in self.hosts:
            return self.hosts[key]

        raise NoHostError('No such host: {0}'.format(key))

    def __getattr__(self, key):
        '''
        DEPRECATED: please use ``Inventory.get_group`` instead.
        '''

        # COMPAT w/ <0.4
        # TODO: remove this function

        logger.warning((
            'Use of Inventory.<group_name> is deprecated, '
            'please use `Inventory.get_group` instead.'
        ))

        if key in self.groups:
            return self.groups[key]

        raise NoGroupError('No such group: {0}'.format(key))

    def __len__(self):
        '''
        Returns the number of active inventory hosts.
        '''

        if not self.state or not self.state.active_hosts:
            return len(self.hosts)

        return len(self.state.active_hosts)

    def __iter__(self):
        '''
        Iterates over active inventory hosts.
        '''

        if not self.state or not self.state.active_hosts:
            return six.itervalues(self.hosts)

        return iter(self.state.active_hosts)

    def len_all_hosts(self):
        '''
        Returns the number of hosts in the inventory, active or not.
        '''

        return len(self.hosts)

    def iter_all_hosts(self):
        '''
        Iterates over all inventory hosts, active or not.
        '''

        return six.itervalues(self.hosts)

    def get_host(self, name, default=NoHostError):
        '''
        Get a single host by name.
        '''

        if name in self.hosts:
            return self.hosts[name]

        if default is NoHostError:
            raise NoHostError('No such host: {0}'.format(name))

        return default

    def get_group(self, name, default=NoGroupError):
        '''
        Get a list of hosts belonging to a group.
        '''

        if name in self.groups:
            return self.groups[name]

        if default is NoGroupError:
            raise NoGroupError('No such group: {0}'.format(name))

        return default

    def get_data(self):
        '''
        Get the base/all data attached to this inventory.
        '''

        return self.data

    def get_override_data(self):
        '''
        Get override data for this inventory.
        '''

        return self.override_data

    def get_host_data(self, hostname):
        '''
        Get data for a single host in this inventory.
        '''

        return self.host_data.get(hostname, {})

    def get_group_data(self, group):
        '''
        Get data for a single group in this inventory.
        '''

        return self.group_data.get(group, {})

    def get_groups_data(self, groups):
        '''
        Gets aggregated data from a list of groups. Vars are collected in order so, for
        any groups which define the same var twice, the last group's value will hold.
        '''

        data = {}

        for group in groups:
            data.update(self.get_group_data(group))

        return data

    def get_deploy_data(self):
        '''
        Gets any default data attached to the current deploy, if any.
        '''

        if self.state and self.state.deploy_data:
            return self.state.deploy_data

        return {}
