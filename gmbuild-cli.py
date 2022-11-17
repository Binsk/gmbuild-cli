#!/bin/python
"""
	AUTHOR:	Reuben Shea
	DATE:	July, 2022

	ABOUT:
	This is a very simplistic application meant to simplify compiling GameMaker projects through
	WINE without requiring the IDE to be open. The goal is to allow full development through 
	external tools and 3rd-party IDEs, such as GMEdit, while still being able to utilize GameMaker's 
	compiler.

	This software is designed solely with Linux in mind and most of the compiling / external calls
	have been reverse-engineered so issues are likely to arise with version changes of GameMaker.
"""

# TODO:	Check why the debug flag isn't working
# TODO:	Test w/ newer runtimes and see if it still works (if not, adjust)
# TODO:	Add support to compile for Linux (from Windows)

import sys,os
import curses
import subprocess
import re
import json
import time

# NOTE: Non-blocking async read is a tweaked version of this gist:
# 	https://gist.github.com/EyalAr/7915597
from threading import Thread
from queue import Queue, Empty

class AsyncRead:
	def __init__(self, iostream):
		self.iostream = iostream        # Stream of data to read from
		self.queue = Queue()            # Queue of results from the string
		self.is_running = True
		def read_io(self, iostream, queue):
			while self.is_running:
				line = iostream.readline()
				if line:
					queue.put(line)

		self.process = Thread(target = read_io, args = (self, self.iostream, self.queue))
		self.process.start()

	def readline(self, timeout=None):
		try:
			return self.queue.get(block = timeout is not None, timeout = timeout)

		except Empty:
			return None
	def terminate(self):
		self.is_running = False
		self.process.join()

# Global variables:
command_list = ["exit", "quit", "print runtimes", "set gm runtime", "set gamemaker runtime", "set debug", "build wine", 
		"set wine drive", "set wine prefix", "set gamemaker project", "set gm project", "clean wine build",
		"build wine existing", "kill wineserver", "export autoload", "set gm config", "set gamemaker config"]
for i in range(0, len(command_list)):
	command_list.append("help " + command_list[i])
command_list.append("help")
command_list.sort()

wine_path = "/home/$USER/.wine" 	# Location of root WINE prefix
wine_gm_path = ""	# Location of GM windows executable
wine_gm_runtime_path = ""	# Path w/o runtime version
wine_gm_runtime = ""	# Name of runtime folder w/o path
wine_gm_runtime_index = -1	# Index in list of runtimes
wine_gm_debug_mode = 0	# False / True
wine_gm_user_dir = ""	# Auto-scanned
wine_local_drive = "Z"	# Local WINE drive that represents root
wine_local_drive_index = -1
system_user = "" 	# Linux user name (used in WINE paths)
system_project_directory = ""
system_project_path = ""
system_project_name = ""
wine_gm_config = "Default"
wine_gm_config_index = 0
wine_gm_lts_suffix = ""

cache_bff_data = {}

	# GameMaker doesn't follow the JSON spec so we need to remove some
	# extra commas or else the JSON parser crashes. Could use YAML but... eh.
def json_strip_dead_commas(string):
	string = re.sub(",[\\s\\t\\n]*\\}", "}", string)
	string = re.sub(",[\\s\\t\\n]*\\]", "]", string)
	return string

# @STUB Wrapper until I find a solution to this problem
def addstr(stdscr, y, x, str):
	is_success = False
	cutoff = 0
	while not is_success and cutoff < len(str):
		try:
			# @STUB For now, cut down string if it overflows
			if cutoff == 0:
				stdscr.addstr(y, x, str)
				is_success = True
			else:
				stdscr.addstr(y, x, str[:-cutoff])
				is_success = True
		except:
			cutoff += 1
		#height, width = stdscr.getmaxyx()
		#subprocess.run(["echo \"ERROR:\n\tX,Y: {},{}\n\tString: {}\n\tString Len: {}\n\tWindow W,H: {}, {}\" >> ./gmbuild.log".format(x, y, str, len(str), width, height)], stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=True)

def get_is_regex_command(str, command):
	pattern = command.replace(" ","\\s*")
	pattern = "^\\s*(help\\s*)?" + pattern + "\\s*$"
	return re.compile(pattern).match(str)

# Creates directories / files w/ default values
def write_default_files():
	global cache_bff_data
	# Generate base WINE project folder:
	subprocess.run(["mkdir {}/drive_c/users/gmbuild".format(wine_path)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	subprocess.run(["mkdir {}/drive_c/users/gmbuild/cache".format(wine_path)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	subprocess.run(["mkdir {}/drive_c/users/gmbuild/temp".format(wine_path)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	subprocess.run(["mkdir {}/drive_c/users/gmbuild/build".format(wine_path)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	subprocess.run(["mkdir {}/drive_c/users/gmbuild/cache/ide".format(wine_path)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	subprocess.run(["mkdir {}/drive_c/users/gmbuild/cache/ide/{}".format(wine_path, system_project_name)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	wine_path_mod = wine_path.replace("$USER", system_user, 1)

	with open("{}/drive_c/users/gmbuild/build.bff".format(wine_path_mod), "w") as file:
		cache_bff_data = generate_bff()
		file.write(json.dumps(cache_bff_data, indent=4))
		file.close()
	with open("{}/drive_c/users/gmbuild/macros.json".format(wine_path_mod), "w") as file:
		file.write(json.dumps(generate_macros(), indent=4))
		file.close()
	with open("{}/drive_c/users/gmbuild/targetoptions.json".format(wine_path_mod), "w") as file:
		file.write(json.dumps(generate_targetoptions(), indent=4))
		file.close()

def generate_targetoptions():
	options = {"runtime" : "VM"}
	return options

def generate_macros():
	wine_path_mod = wine_path.replace("$USER", system_user, 1)

	gmac_path = ""
	bashresult = subprocess.run(["find \"{}\" -type f -name \"GMAssetCompiler.exe\" | head -1".format(wine_gm_runtime_path + wine_gm_runtime)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	gmac_path = str(bashresult.stdout)[2:-3]

	runner_path = ""
	bashresult = subprocess.run(["find \"{}\" -type f -name \"Runner.exe\" | head -2 | grep -v x64".format(wine_gm_runtime_path + wine_gm_runtime)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	runner_path = str(bashresult.stdout)[2:-3]

	runner64_path = ""
	bashresult = subprocess.run(["find \"{}\" -type f -name \"Runner.exe\" | head -2 | grep x64".format(wine_gm_runtime_path + wine_gm_runtime)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	runner64_path = str(bashresult.stdout)[2:-3]

	macros = {
		"asset_compiler_cache_directory" : "{}:{}/drive_c/users/gmbuild/cache/ide".format(wine_local_drive, wine_path_mod),
		"project_cache_directory_name" : system_project_name,
		"project_name" : system_project_name,
		"asset_compiler_path" : "{}:{}".format(wine_local_drive, gmac_path),
		"runner_path" : "{}:{}".format(wine_local_drive, runner_path),
		"x64_runner_path" : "{}:{}".format(wine_local_drive, runner_path),
	}
	return macros

def generate_bff():
	global wine_gm_runtime
	global wine_local_drive
	global wine_gm_lts_suffix
	wine_path_mod = wine_path.replace("$USER", system_user, 1)
	json = {
		"targetFile": "",
		"assetCompiler": "",
		"debug": ("false", "true")[wine_gm_debug_mode],
		"compile_output_file_name": "{}:{}/drive_c/users/gmbuild/build/{}.win".format(wine_local_drive, wine_path_mod, system_project_name),
		"useShaders": "True",
		"steamOptions" : "{}:{}/drive_c/users/gmbuild/steam_options.yy".format(wine_local_drive, wine_path_mod),
		"config" : wine_gm_config,
		"configParents": "",
		"outputFolder" : "{}:{}/drive_c/users/gmbuild/build".format(wine_local_drive, wine_path_mod),
		"projectName" : system_project_name,
		"macros" : "{}:{}/drive_c/users/gmbuild/macros.json".format(wine_local_drive, wine_path_mod),
		"projectDir": "{}:{}".format(wine_local_drive, system_project_directory),
		"preferences": "{}:{}/drive_c/users/gmbuild/preferences.yy".format(wine_local_drive, wine_path_mod),
		"projectPath": "{}:{}".format(wine_local_drive, system_project_path),
		"tempFolder": "{}:{}/drive_c/users/gmbuild/temp".format(wine_local_drive, wine_path_mod),
		"tempFolderUnmapped": "{}:{}/drive_c/users/gmbuild/temp".format(wine_local_drive, wine_path_mod),
		"userDir" : wine_gm_user_dir,
		"runtimeLocation": "{}:{}/drive_c/ProgramData/GameMakerStudio2{}/Cache/Runtimes/{}".format(wine_local_drive, wine_path_mod, wine_gm_lts_suffix, wine_gm_runtime),
		"targetOptions" : "{}:{}/drive_c/users/gmbuild/targetoptions.json".format(wine_local_drive, wine_path_mod),
		"targetMask": "64",
		"applicationPath": "{}:{}".format(wine_local_drive, wine_gm_path),
		"verbose": "False",
		"SteamIDE": "False",
		"helpPort": "51290",
		"debuggerPort": "6509"
	}
	return json

def find_gm_user_dir(history):
	global wine_gm_user_dir
	wine_path_mod = wine_path.replace("$USER", system_user, 1)
	bashresult = subprocess.run(["find \"{}\" -name \"Manifest.enc\" | head -1".format(wine_path_mod)],shell=True,stdout=subprocess.PIPE);
	wine_gm_user_dir = str(bashresult.stdout)[2:-3].replace("/Manifest.enc", "")
	if bashresult.returncode == 1 or len(wine_gm_user_dir.strip()) <= 2:
		history.append("[!] failed to locate GameMaker user login data!");
		wine_gm_user_dir = ""
		return

	history.append("found GameMaker user data in {}".format(wine_gm_user_dir))

# Performs a very simplistic command match:
def get_best_command_match(command):
	best_match_count = 0
	best_match_index = -1

	while command[:1] == " ":
		command = command[1:]

	loop = 0
	for value in command_list:
		min_len = min(len(value), len(command))
		is_match = True;
		for i in range(1, min_len + 1):
			if value[:i] == command[:i]:
				continue;

			is_match = False
			break

		if is_match and best_match_count < min_len:
			best_match_count = min_len
			best_match_index = loop

		loop += 1

	if best_match_index < 0:
		return {"hint" : "", "index" : -1}

	return {
		"hint" : command_list[best_match_index][len(command):],
		"index" : best_match_index
	}

def scan_wine_data(history):
	# Scan for GameMaker executable:
	bashresult = subprocess.run(["find \"{}\" -regextype posix-egrep -type f -regex \".*/GameMaker(Studio|-LTS)?\\.exe\" | head -1".format(wine_path)],shell=True,stdout=subprocess.PIPE);
	global wine_gm_path
	global wine_gm_lts_suffix
	wine_gm_path = str(bashresult.stdout)[2:-3]
	if bashresult.returncode == 1 or len(wine_gm_path.strip()) <= 2:
		history.append("[!] GameMaker executable not found!")
		wine_gm_path = ""
	else:
		history.append("GameMaker executable located at {}".format(wine_gm_path));
		if "-LTS" in wine_gm_path:
			wine_gm_lts_suffix = "-LTS"
		else:
			wine_gm_lts_suffix = ""

def get_prefix_list():
	bashresult = subprocess.run(["find \"/home/{}\" -type d -name \"drive_c\"".format(system_user)],shell=True,stdout=subprocess.PIPE)
	wine_string = str(bashresult.stdout)[2:-3]
	if bashresult.returncode == 1 or len(wine_string.strip()) <= 0:
		return []

	wine_string = wine_string.replace("/drive_c", "")
	list = wine_string.split("\\n")
	list_final = []
	for i in range(0, len(list)):
		if list[i].find("/.directory_history/") >= 0:
			continue

		list_final.append(list[i])

	return list_final

def get_project_list():
	bashresult = subprocess.run(["find \"/home/{}\" -type f -name \"*.yyp\" | grep -iv cache".format(system_user)], shell=True,stdout=subprocess.PIPE);
	project_string = str(bashresult.stdout)[2:-3]
	if bashresult.returncode == 1 or len(project_string.strip()) <= 0:
		return []

	list = project_string.split("\\n")
	return list

def get_runtime_list():
	global wine_gm_path
	global wine_gm_runtime_path

	if wine_gm_path == "":
		return []

	bashresult = subprocess.run(["find \"{}\" -name \"runtimes\" | head -1".format(wine_path)],shell=True,stdout=subprocess.PIPE)
	runtime_path = str(bashresult.stdout)[1:-3] + "'"
	if bashresult.returncode == 1 or len(runtime_path.strip()) <= 2:
		return []

	wine_gm_runtime_path = runtime_path[1:-1] + "/"
	bashresult = subprocess.run(["ls {}".format(runtime_path)], shell=True,stdout=subprocess.PIPE)
	runtime_str = str(bashresult.stdout)[2:-3]
	list = runtime_str.split("\\n")
	return list

def get_config_list():
	global system_project_path
	if system_project_path == "":
		return []

	def scan_for_config(scan_list, final_list, prefix=""):
		for entry in scan_list:
			final_list.append(prefix + entry["name"])
			if len(entry["children"]) > 0:
				scan_for_config(entry["children"], final_list, prefix + entry["name"] + " -> ")

	file = open(system_project_path, "r")
	content = file.read()
	file.close()
	pyobj = json.loads(json_strip_dead_commas(content))
	scan_list = pyobj["configs"]
	final_list = []

	scan_for_config([scan_list], final_list)
	return final_list

def window_select_list(stdscr, titlebar, list, index=0):
	scroll = 0 # Used if window is too small
	lastchar = 0
	if index >= len(list):
		index = 0
	if index < 0:
		index = 0

	while (True):
		stdscr.clear()
		height, width = stdscr.getmaxyx()
		title = "  gmbuild-cli | " + titlebar
		is_too_small = False

		if height < 2 or width < 24:
			try:
				is_too_small = True
				if width > 17:
					title = "window too small"
				else:
					title = "error"
			except:
				stdscr.redraw()

		# Render title bar:
		stdscr.attron(curses.color_pair(3))
		addstr(stdscr, 0, 0, title) # Print title text
		addstr(stdscr, 0, len(title), " " * (width - len(title) - 1)) # Fill remaining column w/ white
		stdscr.attroff(curses.color_pair(3))

		if is_too_small:
			stdscr.refresh()
			# Wait for next input
			lastchar = stdscr.getch()
			continue;

			# Safeguard loop namely for initialization
		while index >= height + scroll - 1:
			scroll += 1

		if lastchar == curses.KEY_DOWN:
			index += 1
			if index >= len(list):
				index = 0
				scroll = 0
			if index - scroll >= height - 1:
				scroll += 1
		elif lastchar == curses.KEY_UP:
			index -= 1
			if index < 0:
				index = len(list) - 1
				scroll = max(0, len(list) - height + 1)
			if index < scroll:
				scroll -= 1
		elif lastchar == 10:
			break

		for i in range(scroll + 1, min(height - 1 + scroll, len(list)) + 1):
			if i - 1 == index:
				stdscr.attron(curses.color_pair(4))
			else:
				stdscr.attron(curses.color_pair(1))

			addstr(stdscr, i - scroll, 2, list[i - 1])

			if i - 1 == index:
				stdscr.attroff(curses.color_pair(4))
			else:
				stdscr.attroff(curses.color_pair(1))

		# Refresh the screen:
		stdscr.move(0, width - 1)
		stdscr.refresh()

		# Wait for next input
		lastchar = stdscr.getch()

	return index

def window_run_wine(stdscr, titlebar, output_history, use_existing=False):
	global wine_gm_runtime
	global cache_bff_data
	is_output_paused = False	# Used to allow reading outputy
	paused_start_index = 0		# Only print until this index if output is paused
	compile_start_index = len(output_history)	# Where to start if we dump
	instance_count = 1	# Number of instances of the game
	if use_existing:
		bashscript = "find \"{}\" -name \"build.bff\" | head -1".format(wine_path)
		result = subprocess.run([bashscript],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
		bff_path = str(result.stdout)[1:-3] + "'"
		if result.returncode != 0 or len(bff_path) <= 2:
			output_history.append("[!] no build.bff file found!")
			return

		try:
			# Attempt to read the runtime version from the pre-generated build file:
			file = open(bff_path[1:-1], "r")
			content = file.read()
			file.close()
			pyobj = json.loads(content)
			runtime = re.findall("runtime-[0-9.]+$", pyobj["runtimeLocation"])[0]
			output_history.append("[!] runtime set to {}".format(runtime));
			wine_gm_runtime = runtime
		except:
			output_history.append("[!] error reading build.bff!")
			return
	else:
		wine_path_mod = wine_path.replace("$USER", system_user, 1)
		bff_path = "{}:{}/drive_c/users/gmbuild/build.bff".format(wine_local_drive, wine_path_mod)

	igorpath = ""
	bashresult = subprocess.run(["find \"{}\" -type f -name \"Igor.exe\" | head -1".format(wine_gm_runtime_path + wine_gm_runtime)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	igorpath = str(bashresult.stdout)[2:-3]
	if bashresult.returncode == 1 or len(wine_gm_user_dir.strip()) <= 2:
		output_history.append("[!] failed to find Igor.exe!")
		return

	bashscript = "env WINEPREFIX=\"{}\" env WINEDEBUG=\"warn-all,fixme-all,trace-all,err-all\" wine \"{}\" -options={} -v -- Windows Run".format(wine_path, igorpath, bff_path)
#	bashscript = "env WINEPREFIX=\"{}\" wine \"{}\" -options={} -v -- Windows Run".format(wine_path, igorpath, bff_path)
	process = subprocess.Popen([bashscript],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)

	asyncprocess_list = [AsyncRead(process.stdout)]
#	asyncprocess_list = [AsyncRead(process.stderr)]

	stdscr.nodelay(True)
	lastchar = 0
	time_last = time.time() - 0.1 # in S, update every 100

	last_height = 0
	last_width = 0

	while True:
		line_array = []
		# Grab lines for 0.1s or until a keypress is registered:
		# NOTE: The 0.1s delay is to help w/ ncurses flickering
		while True:
			try:
				time_current = time.time()
				line = asyncprocess_list[0].readline(1) # Timeout if no new input, otherwise async
				if not line:
					break

				line_array.append(str(line)[2:-5])
				if time_current - time_last >= 0.1:
					break
			except:
				break

		time_last = time.time() # MS, update every 100
		for line in line_array:
			output_history.append(str(line))

		height, width = stdscr.getmaxyx()

		if last_height != height or last_width != width:
			stdscr.clear()
			last_height = height
			last_width = width

		title = "  gmbuild-cli | " + titlebar
		is_too_small = False
		if height < 3 or width < 32:
			try:
				is_too_small = True
				if width > 17:
					title = "window too small"
				else:
					title = "error"
			except:
				stdscr.refresh()

		stdscr.attron(curses.color_pair(3))
		addstr(stdscr, 0, 0, title)
		addstr(stdscr, 0, len(title), " " * (width - len(title) - 1))
		stdscr.attroff(curses.color_pair(3))

		if is_too_small:
			stdscr.refresh()
			continue

		# Output instruction line:
		stdscr.attron(curses.color_pair(3))
		hint = "  [Q] kill wineserver"
		if is_output_paused:
			hint += " | [P] resume output"
		else:
			hint += " | [P] pause output"

		hint2 = "  [D] dump output    "
		hint2 += " | [X] launch instance {}".format(instance_count + 1)

		try:
			addstr(stdscr, height - 2, 0, hint)
			addstr(stdscr, height - 2, len(hint), " " * (width - len(hint)))
			addstr(stdscr, height - 1, 0, hint2)
			addstr(stdscr, height - 1, len(hint2), " " * (width - len(hint2)))
		except:
			stdscr.refresh()
			height, width = stdscr.getmaxyx()

		stdscr.attroff(curses.color_pair(3))

		# Handle 'close' input
		break_loop = False
		if lastchar == ord('q') or lastchar == ord('Q'):
			break_loop = True
			output_history.append("killing WINE server...")
		elif lastchar == ord('p') or lastchar == ord('P'):
			output_history.append("[!] output paused, WINE server running in the background...")
			is_output_paused = not is_output_paused
			paused_start_index = len(output_history) - 1 # Account for just appended line

		if not is_output_paused:
			paused_start_index = len(output_history) - 1

		if lastchar == ord('d') or lastchar == ord('D'):
			paused_start_index += 1
			try:
				file = open("/home/{}/dump.log".format(system_user), "w")
				log_copy = output_history[compile_start_index:paused_start_index]
				file.write("\n".join(log_copy))
				file.close()
				output_history.insert(paused_start_index, "[!] dumped output to ~/dump.log")
			except:
				output_history.insert(paused_start_index, "[!] failed to dump log!")
		elif lastchar == ord('x') or lastchar == ord('X'):
			instance_count += 1
			try:

				wine_path_mod = wine_path.replace("$USER", system_user, 1)
				runpath = ""
				bashresult = subprocess.run(["find \"{}\" -type f -name \"Runner.exe\" | head -1".format(wine_gm_runtime_path + wine_gm_runtime)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
				runpath = str(bashresult.stdout)[2:-3]
				bashscript = "env WINEPREFIX=\"{}\" env WINEDEBUG=\"warn-all,fixme-all,trace-all,err-all\" wine \"{}\" -game \"{}\"".format(wine_path, runpath, cache_bff_data["compile_output_file_name"])
				process = subprocess.Popen([bashscript],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
				asyncprocess_list.append(AsyncRead(process))
				paused_start_index += 1
				output_history.insert(paused_start_index, "[!] launched game instance {}".format(instance_count))
			except:
				paused_start_index += 1
				output_history.insert(paused_start_index, "[!] failed to launch new instance!")
				instance_count -= 1

		# Output history (and thus incoming terminal info):
		print_history(stdscr, output_history, paused_start_index, -1)

		stdscr.move(0, width - 1)
		stdscr.refresh()

		if break_loop:
			break

		lastchar = stdscr.getch()

	# Trigger killing the wineserver if not already killed:
	subprocess.run(["env WINEPREFIX=\"{}\" wineserver -k".format(wine_path)], shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
	# Tell the iothread to die and wait until it closes:
	for thread in asyncprocess_list:
		thread.terminate()

	output_history.append("[!] WINE server killed...")
	stdscr.nodelay(False)
	return

def print_history(stdscr, output_history, start_index=-1, yoff=0):
	height, width = stdscr.getmaxyx()
	output_history_y = height - 2 + yoff

	if start_index < 0:
		start_index += len(output_history)
	for i in range(start_index, 0, -1):
		value = output_history[i]
		if output_history_y < 1:
			break

		value = value.strip()
		is_urgent = False
		if value.startswith("[!]"):
			stdscr.attron(curses.color_pair(2))
			is_urgent = True

		if len(": " + value) < width:
			addstr(stdscr, output_history_y, 0, ": " + value)
			addstr(stdscr, output_history_y, len(": " + value), " " * (width - len(": " + value) - 1))
		else:
			value_list = []
			value_mod = value
			while len(value_mod) >= width - 2:
				value_list.append(value_mod[:width - 7])
				value_mod = value_mod[width - 7:]

			if len(value_mod) > 0:
				value_list.append(value_mod)

			for i in range(0, len(value_list)):
				if output_history_y < 1:
					break

				subvalue = value_list[len(value_list) - 1 - i]
				if len(subvalue) <= 0:
					continue
				if i == len(value_list) - 1:
					subvalue = ": " + subvalue + "..."
				elif i > 0:
					subvalue = "  " + subvalue + "..."
				else:
					subvalue = "  " + subvalue

				addstr(stdscr, output_history_y, 0, subvalue);
				addstr(stdscr, output_history_y, len(subvalue), " " * (width - len(subvalue) - 1))

				output_history_y -= 1

			if is_urgent:
				stdscr.attroff(curses.color_pair(2))
			continue

		output_history_y -= 1
		if is_urgent:
			stdscr.attroff(curses.color_pair(2))

def import_autoload():
	global system_user
	global system_project_path
	global wine_path
	global wine_gm_runtime_path
	global wine_gm_debug_mode
	global wine_local_drive
	global wine_gm_runtime
	global wine_gm_config
	global wine_gm_lts_suffix
	try:
		file = open("/home/{}/.gmbuild_autoload".format(system_user))
		content = file.read()
		file.close()
		data = json.loads(content)
		system_project_path = data["ppath"]
		wine_path = data["prefix"]
		wine_gm_runtime_path = data["rtpath"]
		wine_gm_runtime = data["rt"]
		wine_gm_debug_mode = data["debug"]
		wine_local_drive = data["drive"]
		wine_gm_config = data["config"]
		wine_gm_lts_suffix = data["lts"]
	except:
		return False

	return True

def curses_main(stdscr):
	global wine_gm_runtime
	global wine_gm_runtime_index
	global wine_gm_debug_mode
	global wine_local_drive_index
	global wine_local_drive
	global wine_path
	global system_project_name
	global system_project_directory
	global system_project_path
	global wine_gm_config
	global wine_gm_config_index
	global wine_gm_lts_suffix

	lastchar = 0
	inputstr = ""
	input_x = 0	# Cursor relative to the input string
	output_history = []	# All history
	input_history = []	# User-inputted history
	input_history_index = -1

	# Clear / refresh the screen:
	stdscr.clear()
	stdscr.refresh()

	# Support colors:
	curses.start_color()
	curses.use_default_colors()
	curses.init_pair(1, curses.COLOR_CYAN, -1)
	curses.init_pair(2, curses.COLOR_RED, -1)
	curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)
	curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN)

	try:
		addstr(stdscr, 0, 0, "Please wait...")
		stdscr.refresh()
	except:
		stdscr.clear()

	is_autoload = import_autoload()

	# Show default wine prefix selection list:
	if is_autoload:
		output_history.append("WINE prefix set to {}".format(wine_path))
		find_gm_user_dir(output_history)
	else:
		prefix_list = get_prefix_list()
		if len(prefix_list) > 0:
			wine_path_index = window_select_list(stdscr, "set wine prefix", prefix_list)
			wine_path = prefix_list[wine_path_index]
			output_history.append("WINE prefix set to {}".format(wine_path))
			find_gm_user_dir(output_history)
		else:
			output_history.append("[!] no wine prefixes found!")

	scan_wine_data(output_history)

	# Show default runtime selection list:
	if is_autoload:
		output_history.append("GameMaker runtime set to {}".format(wine_gm_runtime))
	else:
		runtime_list = get_runtime_list()
		if len(runtime_list) > 0:
			wine_gm_runtime_index = window_select_list(stdscr, "set runtime", runtime_list)
			wine_gm_runtime = runtime_list[wine_gm_runtime_index]
			output_history.append("GameMaker runtime set to {}".format(wine_gm_runtime))
		else:
			output_history.append("[!] no runtimes found, are they installed?")

	# Show default GameMaker project selection list:
	if is_autoload:
		system_project_name = re.findall("/[a-zA-Z.\\s0-9-]+\.yyp$", system_project_path)[0][1:-4]
		system_project_directory = system_project_path.replace(system_project_name + "yyp", "")
		output_history.append("project set to {}".format(system_project_name))
	else:
		project_list = get_project_list()
		if len(project_list) > 0:
			try:
				project_path_index = window_select_list(stdscr, "set gamemaker project", project_list)
				system_project_path = project_list[project_path_index]
				system_project_name = re.findall("/[a-zA-Z.\\s0-9-]+\.yyp$", system_project_path)[0][1:-4]
				system_project_directory = system_project_path.replace(system_project_name + "yyp", "")
				output_history.append("project set to {}".format(system_project_name))
			except:
				output_history.append("[!] error processing project name (invalid characters?)")
		else:
			output_history.append("[!] no GameMaker projects found!")

	output_history.append("config set to {}".format(wine_gm_config))
	if is_autoload:
		wine_gm_runtime_index = 0
		output_history.append("finished performing autoload, to prevent this in the future delete ~/.gmbuild_autoload")

	last_height = 0
	last_width = 0

	# Loop where 'lastchar' is the last character pressed:
	while (True):
		# Prepare to update the screen
		height, width = stdscr.getmaxyx()
		is_too_small = False
		title = "  gmbuild-cli"

		if height < 3 or width < 24:
			is_too_small = True
			if width > 17:
				title = "Window too small!"
			else:
				title = "[error]"

		if last_height != height or last_width != width:
			stdscr.clear()
			last_height = height
			last_width = width

		# Render title bar:
		stdscr.attron(curses.color_pair(3))
		addstr(stdscr, 0, 0, title) # Print title text
		addstr(stdscr, 0, len(title), " " * (width - len(title) - 1)) # Fill remaining column w/ white
		stdscr.attroff(curses.color_pair(3))

		if is_too_small:
			stdscr.refresh()
			# Wait for next input
			lastchar = stdscr.getch()
			continue;

		# Render input:
		inputstr_lower = inputstr.lower()

		if lastchar in range(32,126):
			inputstr = inputstr[:input_x] + chr(lastchar) + inputstr[input_x:]
			input_x += 1
		else: # Handle cursor movement:
			if lastchar == 263 and input_x > 0: # Backspace
				inputstr = inputstr[:input_x-1] + inputstr[input_x:]
				input_x -= 1
			elif lastchar == 260 and input_x > 0: # Left-arrow
				input_x -= 1
			elif lastchar == 261 and input_x < len(inputstr): # Right-arrow
				input_x += 1
			elif lastchar == 262: # HOME
				input_x = 0
			elif lastchar == 360: # END
				input_x = len(inputstr) + 1
			elif lastchar == 259: # UP
				input_history_index = max(input_history_index - 1, 0)
				if input_history_index < len(input_history):
					inputstr = input_history[input_history_index]

				input_x = len(inputstr)
			elif lastchar == 258: # DOWN
				input_history_index = min(input_history_index + 1, len(input_history) - 1)
				if input_history_index >= 0:
					inputstr = input_history[input_history_index]

				input_x = len(inputstr)
			elif lastchar == 21: # CTRL+U
				input_x = 0
				inputstr = ""
			elif lastchar == 261 or lastchar == 9: # RIGHT / LTAB
				index = get_best_command_match(inputstr)["index"]
				if index >= 0:
					inputstr = command_list[index]
					input_x = len(inputstr)
			elif lastchar == 10: # ENTER
				input_x = 0
				if len(inputstr.strip()) > 0:
					output_history.append(inputstr)
					input_history.append(inputstr)

				input_history_index = len(input_history)
				inputstr = ""
				is_help = (inputstr_lower.find("help") >= 0)

				if get_is_regex_command(inputstr_lower, "exit"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("immediately terminates the program")
					else:
						break
				elif get_is_regex_command(inputstr_lower, "print runtimes"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("lists recognized GameMaker build runtimes")
					else:
						runtime_list = get_runtime_list()
						if len(runtime_list) == 0:
							output_history.append("no runtimes found!")
						else:
							for value in runtime_list:
								output_history.append("\t{}".format(value))
				elif get_is_regex_command(inputstr_lower,"set (gm|gamemaker) runtime"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("opens a list to select which GameMaker runtime to compile with")
					else:
						runtime_list = get_runtime_list()
						if len(runtime_list) == 0:
							output_history.append("[!] no runtimes found!")
						else:
							wine_gm_runtime_index = window_select_list(stdscr, "set runtime", runtime_list, wine_gm_runtime_index)
							wine_gm_runtime = runtime_list[wine_gm_runtime_index]
							output_history.append("GameMaker runtime set to {}".format(wine_gm_runtime))
				elif get_is_regex_command(inputstr_lower,"set (gm|gamemaker) config"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("opens a list to select which GameMaker config to compile with")
					else:
						config_list = get_config_list()
						if len(config_list) == 0:
							output_history.append("[!] no configs found!")
						else:
							wine_gm_config_index = window_select_list(stdscr, "set config", config_list, wine_gm_config_index)
							match_array = re.findall("-> \\w*$", config_list[wine_gm_config_index])
							if len(match_array) > 0:
								wine_gm_config = match_array[0][3:]
							else:
								wine_gm_config = config_list[wine_gm_config_index]
							output_history.append("GameMaker config set to {}".format(wine_gm_config))
				elif get_is_regex_command(inputstr_lower, "set debug"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("opens a list to select whether or not to compile with debugging enabled")
					else:
						wine_gm_debug_mode = window_select_list(stdscr, "debug mode", ["disabled", "enabled"], wine_gm_debug_mode)
						output_history.append("debug mode {}".format("enabled" if wine_gm_debug_mode == 1 else "disabled"))
				elif get_is_regex_command(inputstr_lower, "set wine drive"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("opens a list to select which drive letter is being used by WINE to point to drive's root directory")
					else:
						letter_list = ["A",'B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S','T','U','V','W','X','Y','Z']
						if wine_local_drive_index < 0:
							wine_local_drive_index = len(letter_list) - 1

						wine_local_drive_index = window_select_list(stdscr, "set wine drive letter", letter_list, wine_local_drive_index)
						wine_local_drive = letter_list[wine_local_drive_index]
						output_history.append("WINE drive specified as {}:\\".format(wine_local_drive))
				elif get_is_regex_command(inputstr_lower, "set wine prefix"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("opens a list to select which WINE prefix should be used and scanned for GameMaker executables")
					else:
						prefix_list = get_prefix_list()
						if len(prefix_list) > 0:
							wine_path_index = window_select_list(stdscr, "set wine prefix", prefix_list)
							wine_path = prefix_list[wine_path_index]
							output_history.append("WINE prefix set to {}".format(wine_path))
							find_gm_user_dir(output_history);
							scan_wine_data(output_history)
							output_history.append("[!] please select a valid runtime!")
							wine_gm_runtime = ""
							wine_gm_runtime_index = -1
						else:
							output_history.append("[!] no wine prefixes found!")
				elif get_is_regex_command(inputstr_lower, "set (gamemaker|gm) project"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("opens a list to select which GameMaker project should be compiled on the next build")
					else:
						project_list = get_project_list()
						if len(project_list) > 0:
							try:
								project_path_index = window_select_list(stdscr, "set gamemaker project", project_list)
								system_project_path = project_list[project_path_index]
								system_project_name = re.findall("/[a-zA-Z.\\s0-9-]+\.yyp$", system_project_path)[0][1:-4]
								system_project_directory = system_project_path.replace(system_project_name + "yyp", "")
								wine_gm_config = "Default"
								wine_gm_config_index = 0
								output_history.append("project set to {}".format(system_project_name))
							except:
								output_history.append("[!] error processing project name (invalid characters?)")
						else:
							output_history.append("[!] no GameMaker projects found!")
				elif get_is_regex_command(inputstr_lower, "kill wineserver"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("forcefully kills any background running WINE processes")
					else:
						subprocess.run(["wineserver -k"], shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
						output_history.append("WINE server killed...")
				elif get_is_regex_command(inputstr_lower, "build wine(\\s*existing)?"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("begins a build of the currently active project")
						output_history.append("if 'existing' is specified the first build-properties file found in the active WINE prefix will be used instead of generating a new file")
					else:
						is_valid = True
						if len(system_project_name) <= 0:
							is_valid = False
							output_history.append("[!] please select a valid GameMaker project before building!")

						if wine_gm_runtime_index < 0:
							is_valid = False
							output_history.append("[!] please select a valid runtime before building!")

						if is_valid:
							write_default_files() # Generate required files for the build
							stdscr.clear()
							window_run_wine(stdscr, "running program...", output_history, inputstr_lower.find("existing") >= 0)
							stdscr.clear()
							continue
				elif get_is_regex_command(inputstr_lower, "clean wine build"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("deletes all cached GameMaker builds and build files")
					else:
						subprocess.run(["rm -rf {}/drive_c/users/gmbuild".format(wine_path)],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
						output_history.append("build files removed")

				elif get_is_regex_command(inputstr_lower, "export autoload"):
					if is_help:
						output_history.append("[!] info:")
						output_history.append("exports build settings to your home directory to be auto-loaded next startup")
					else:
						try:
							data = {
								"ppath" : system_project_path,
								"prefix" : wine_path,
								"rtpath" : wine_gm_runtime_path,
								"rt" : wine_gm_runtime,
								"debug" : wine_gm_debug_mode,
								"drive" : wine_local_drive,
								"config" : wine_gm_config,
								"lts" : wine_gm_lts_suffix
							}
							file = open("/home/{}/.gmbuild_autoload".format(system_user), "w")
							file.write(json.dumps(data))
							file.close()
							output_history.append("autoload exported, to prevent autoload delete ~/.gmbuild_autoload")
						except:
							output_history.append("failed to write autoload file")
				elif re.compile("^\\s*help*\\s*$").match(inputstr_lower):
					output_history.append("[!] info:")
					output_history.append("available commands:")
					for value in command_list:
						if value.find("help") >= 0:
							continue

						output_history.append("- " + value)
					output_history.append("you can find more info on a specific command by typing `help [command]`")
				elif not re.compile("^[\\s\\t]*$").match(inputstr_lower):
					output_history.append("invalid command!");

		# Clear input line:
		addstr(stdscr, height - 1, 0, " " * (width - 1))

		# Add prompt:
		addstr(stdscr, height - 1, 0, "> " + inputstr)

		# Render hint:
		stdscr.attron(curses.color_pair(1))
		addstr(stdscr, height - 1, len("> " + inputstr), get_best_command_match(inputstr)["hint"])
		stdscr.attroff(curses.color_pair(1))

		# Output history:
		print_history(stdscr, output_history)

		# Adjust visual cursor back to input:
		stdscr.move(height - 1, len("> ") + input_x)

		# Refresh the screen:
		stdscr.refresh()

		# Wait for next input
		lastchar = stdscr.getch()

def main():
	global system_user

	result = subprocess.run(["printf $USER"],shell=True,stdout=subprocess.PIPE)
	if result.returncode != 0:
		print("Failed to fetch system user name, exiting...")
		return

	system_user = str(result.stdout)[2:-1]

	# Check that we have required tools installed:
	bashscript = "if ! hash wine; then exit 1; else exit 0; fi"
	if subprocess.run([bashscript],shell=True).returncode != 0:
		print ("WINE is not installed, exiting...")
		return

	# Start curses:
	curses.wrapper(curses_main)

if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		subprocess.run(["wineserver -k"],shell=True) # Kill any WINE processes just in case
		sys.exit(0)
