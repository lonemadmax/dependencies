#!/bin/python3
#
# Copyright 2023, Haiku, Inc. All rights reserved.
# Distributed under the terms of the MIT License.
#

import argparse
from collections import defaultdict
from pathlib import Path
import subprocess


WARNING = '''Be aware that this program:
* assumes things that may be wrong (that there's no more detail here should make you afraid of using its output for anything important)
* does not check versions (if A provides dep=1, B provides dep=2 and C requires dep>=2, it will list both A and B as dependencies of C)
* does not know if a package was installed on purpose or as a dependency
* understands 'supplements' as 'requires'
* does not look for disjoint sets
* sloppily parses the output of the 'package' command run on each of the package files found
'''

def extract_entity(line):
	entity = line[line.find(':') + 2:]
	forbidden = '-=>!</'
	for i, char in enumerate(entity):
		if char.isspace() or char in forbidden:
			return entity[:i]
	return entity

def read_package(package):
	package_info = {
		'name': '',
		'path': package,
		'requires': set(),
		'provides': set(),
	}

	result = subprocess.run(['/bin/package', 'list', '-i', package],
		capture_output=True, check=True, text=True)
	for line in result.stdout.splitlines():
		if line.startswith('\tprovides: '):
			package_info['provides'].add(extract_entity(line))
		elif line.startswith('\trequires: ') or line.startswith('\tsupplements: '):
			package_info['requires'].add(extract_entity(line))
		elif line.startswith('\tname: '):
			package_info['name'] = extract_entity(line)

	return package_info

def finddir(which):
	result = subprocess.run(['/bin/finddir', which], capture_output=True, text=True)
	if result.returncode:
		return ''
	return result.stdout[:-1]

def get_packages():
	packages = []
	for package_dir in ('B_SYSTEM_PACKAGES_DIRECTORY', 'B_USER_PACKAGES_DIRECTORY'):
		package_dir = Path(finddir(package_dir))
		for package_file in package_dir.glob('*.hpkg'):
			packages.append(read_package(package_file))
	return packages

def do_leaves(args):
	if not args.i_know_what_im_doing:
		print(WARNING)
	packages = get_packages()
	requirements = set()
	requirements.update(*(package['requires'] for package in packages))
	for package in packages:
		for entity in package['provides']:
			if entity in requirements:
				break
		else:
			print(package['name'], package['path'])

def escape_DOT_string(string):
	return string.replace('\\"', '\\\\"')

def escape_DOT_label(string, justify='center'):
	string = escape_DOT_string(string)
	string.replace('\\', '\\\\"')
	if justify == 'left':
		sep = '\\l'
	elif justify == 'right':
		sep = '\\r'
	else:
		return string
	return string.replace('\n', sep)

def do_graph(args):
	if args.all_requirements:
		do_requirements_graph(args)
	else:
		do_level1_graph(args)

def do_requirements_graph(args):
	if not args.package:
		raise graph_parser.error('a package list is required with the --all-requirements option')
	packages = get_packages()
	package_map = {}
	providers = defaultdict(list)
	for package in packages:
		name = package['name']
		package['DOT_id'] = '"' + escape_DOT_string(name) + '"'
		package_map[name] = package
		for entity in package['provides']:
			providers[entity].append(name)

	graph_packages = set(args.package)
	visited = set()

	print('digraph {')

	if not args.i_know_what_im_doing:
		print('label="', escape_DOT_label(WARNING, 'left'), '"', sep='')
	print('node [style=filled fillcolor=aliceblue]')
	print('{ node [fillcolor=lightgrey]')
	for package_name in graph_packages:
		if package_name in package_map:
			print(package_map[package_name]['DOT_id'])
		else:
			print('"', escape_DOT_string(package_name), '" [fillcolor=red]', sep='')
			visited.add(package_name)
	print('}')

	while graph_packages:
		package_name = graph_packages.pop()
		if package_name in visited:
			continue
		package = package_map[package_name]
		for entity in package['requires']:
			node = package['DOT_id']
			edge = escape_DOT_label(entity)
			for dependency_name in providers[entity]:
				print(node, ' -> ', package_map[dependency_name]['DOT_id'],
					' [label="', edge, '"]',
					sep='')
				graph_packages.add(dependency_name)
		visited.add(package_name)

	print('}')

def do_level1_graph(args):
	packages = get_packages()
	package_map = {}
	providers = defaultdict(list)
	requirers = defaultdict(list)
	for package in packages:
		name = package['name']
		package['DOT_id'] = '"' + escape_DOT_string(name) + '"'
		package_map[name] = package
		for entity in package['provides']:
			providers[entity].append(name)
		for entity in package['requires']:
			requirers[entity].append(name)
	if args.package:
		graph_packages = set(args.package)
	else:
		graph_packages = set(package_map)

	outside_nodes = set()
	error_nodes = set()
	if args.all_edges:
		class list_with_alias(list):
			def add(self, item):
				self.append(item)
			def update(self, iterable):
				self.extend(iterable)
		edges = defaultdict(list_with_alias)
	else:
		edges = defaultdict(set)

	for package_name in graph_packages:
		try:
			package = package_map[package_name]
		except KeyError:
			error_nodes.add(package_name)
			continue
		dependencies = edges[package_name]
		for entity in package['requires']:
			dependencies.update(providers[entity])
		for dependency in dependencies:
			if dependency not in graph_packages:
				outside_nodes.add(dependency)
		for entity in package['provides']:
			for dependency in requirers[entity]:
				if dependency not in graph_packages:
					outside_nodes.add(dependency)
					edges[dependency].add(package_name)
				# else we'll (or already have) catch this when we process dependency

	print('digraph {')
	print('node [style=filled]')
	if not args.i_know_what_im_doing:
		print('label="', escape_DOT_label(WARNING, 'left'), '"', sep='')
	if error_nodes:
		print('{ node [fillcolor=red]')
		for package in error_nodes:
			print('"', escape_DOT_string(package), '"', sep='')
		print('}')
	if outside_nodes:
		print('{ node [fillcolor=aliceblue]')
		for package in outside_nodes:
			print(package_map[package]['DOT_id'])
		print('}')
	for package, requirements in edges.items():
		package = package_map[package]
		for required_package in requirements:
			print(package['DOT_id'], '->', package_map[required_package]['DOT_id'])
	print('}')


arg_parser = argparse.ArgumentParser(epilog=WARNING,
	formatter_class=argparse.RawDescriptionHelpFormatter)
arg_parser.add_argument('--i-know-what-im-doing', action='store_true',
	help='remove the nagging warnings')
commands = arg_parser.add_subparsers(title='commands', dest='command')

graph_parser = commands.add_parser('graph',
	help='output a DOT graph of dependencies')
graph_parser.add_argument('--all-edges', action='store_true',
	help='draw an edge for every dependency between two packages')
graph_parser.add_argument('--all-requirements', action='store_true',
	help='recursively visit all the requirements of the given packages')
graph_parser.add_argument('package', nargs='*',
	help='''packages to include in the graph (along with their dependencies).
		If no package is specified, use all found ones''')

leaves_parser = commands.add_parser('leaves',
	help='list packages that are not depended on')

arg_parser.set_defaults(command='leaves')

args = arg_parser.parse_args()
{
	'graph': do_graph,
	'leaves': do_leaves,
}[args.command](args)
