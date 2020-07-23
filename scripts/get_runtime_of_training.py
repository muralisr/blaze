import os
import datetime

def get_timestamp_for_dir(dir_path):
	timestamp_str = os.popen(f"date -r {dir_path}").read()
	print(f"got timestamp {timestamp_str}")
	print(f"returning {datetime.datetime.strptime(timestamp_str, '%a %b %d %H:%M:%S %Z %Y')}")
	return datetime.datetime.strptime(timestamp_str, '%a %b %d %H:%M:%S %Z %Y')

list_of_directories = ["www.apple.com__"]
starting_path = "/home/nikhil/ray_results_april_2020_PLT"
directory_to_last_checkpoint_num = {}
directory_to_time_taken = {}
for directory in list_of_directories:
	list_of_checkpoint_dirs = os.listdir(os.path.join(starting_path, directory))
	list_of_checkpoint_dirs = [x for x in list_of_checkpoint_dirs if "checkpoint" in x]
	print(f'list of dirs is {list_of_checkpoint_dirs}')
	list_of_timestamps = [get_timestamp_for_dir(os.path.join(os.path.join(starting_path, directory)), x) for x in list_of_checkpoint_dirs]