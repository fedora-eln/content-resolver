#! /usr/bin/python3

import content_resolver.analyzer
import sys
import urllib.request

# This is a starting point for a test of the function parsing root logs.
# Set the url below to any root log, and then you can see what it detected.

if len(sys.argv) > 1:
    root_log_url = sys.argv[1]
else:
    root_log_url = "https://kojipkgs.fedoraproject.org//packages/gstreamer1-vaapi/1.22.9/1.fc39/data/logs/x86_64/root.log"

request = urllib.request.Request(root_log_url)
request.add_header("Accept", "text/plain")
request.add_header("User-Agent", "ContentResolver/1.0")

with urllib.request.urlopen(request) as response:
    root_log_data = response.read()
    root_log_contents = root_log_data.decode('utf-8')

required_pkg_names = content_resolver.analyzer._get_build_deps_from_a_root_log(root_log_contents)

print(required_pkg_names)
