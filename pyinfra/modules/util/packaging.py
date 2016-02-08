# pyinfra
# File: pyinfra/modules/util/packaging.py
# Desc: common functions for packaging modules

from pyinfra.api.exceptions import PyinfraException


def ensure_packages(
    packages, current_packages, present,
    install_command, uninstall_command,
    latest=False, upgrade_command=None,
    version_join=None, lower=True
):
    '''
    Handles this common scenario:

    + We have a list of packages(/versions) to ensure
    + We have a map of existing package -> versions
    + We have the common command bits (install, uninstall, version "joiner")
    + Outputs commands to ensure our desired packages/versions
    + Optionally upgrades packages w/o specified version when present

    Args:
        packages (list): list of packages or package/versions
        current_packages (fact): fact returning dict of package names -> version
        present (bool): whether packages should exist or not
        install_command (str): command to prefix to list of packages to install
        uninstall_command (str): as above for uninstalling packages
        latest (bool): whether to upgrade installed packages when present
        upgrade_command (str): as above for upgrading
        version_join (str): the package manager specific "joiner", ie ``=`` for \
            ``<apt_pkg>=<version>``
        lower (bool): whether to lowercase package names
    '''

    if latest and not upgrade_command:
        raise PyinfraException(
            'Packages cannot be upgraded to latest w/o upgrade_command'
        )

    if packages is None:
        return []

    commands = []

    # Current packages not strictly required
    if not current_packages:
        current_packages = {}

    # Accept a single package as string
    if isinstance(packages, basestring):
        packages = [packages]

    # Lowercase packaging?
    if lower:
        packages = [
            package.lower()
            for package in packages
        ]

    # Version support?
    if version_join:
        # Split where versions present
        packages = [
            package.split(version_join)
            for package in packages
        ]

        # Covert to either string or list
        packages = [
            package[0] if len(package) == 1
            else package
            for package in packages
        ]

    # Diff the ensured packages against the remote state/fact
    diff_packages = []

    # Packages to upgrade? (install only)
    upgrade_packages = None

    # Installing?
    if present is True:
        diff_packages = [
            package
            for package in packages
            if(
                # Tuple/version, check not in existing OR incorrect version
                isinstance(package, list)
                and (
                    package[0] not in current_packages
                    or package[1] != current_packages[package[0]]
                )
            ) or (
                # String version, just check if not existing
                isinstance(package, basestring)
                and package not in current_packages
            )
        ]

        # Present packages w/o version specified - for upgrade if latest
        upgrade_packages = [
            package
            for package in packages
            if isinstance(package, basestring)
            and package in current_packages
        ]

    # Uninstalling?
    else:
        diff_packages = [
            package
            for package in packages
            if(
                # Tuple/version, check existing AND correct version
                isinstance(package, list)
                and (
                    package[0] in current_packages
                    and package[1] == current_packages[package[0]]
                )
            ) or (
                # String version, just check if existing
                isinstance(package, basestring)
                and package in current_packages
            )
        ]

    # Convert packages back to string(/version)
    diff_packages = [
        version_join.join(package)
        if isinstance(package, list)
        else package
        for package in diff_packages
    ]

    if diff_packages:
        command = install_command if present else uninstall_command

        commands.append('{0} {1}'.format(
            command,
            ' '.join(diff_packages)
        ))

    if latest and upgrade_packages:
        commands.append('{0} {1}'.format(
            upgrade_command,
            ' '.join(upgrade_packages)
        ))

    return commands