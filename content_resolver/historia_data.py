import datetime
import json
import os
import re
from content_resolver.data_generation import _generate_json_file
from content_resolver.utils import dump_data, err_log, log


def _save_current_historic_data(query):
    # This is the historic data for charts
    # Package lists are above

    log("Generating current historic data...")

    # Where to save it
    year = datetime.datetime.now().strftime("%Y")
    week = datetime.datetime.now().strftime("%W")
    filename = f"historic_data-{year}-week_{week}.json"
    output_dir = os.path.join(query.settings["output"], "history")
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, filename)

    # What to save there
    history_data = {
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "workloads": {},
        "envs": {},
        "repos": {},
        "views": {},
    }

    # Workloads
    for workload_id in query.workloads(None,None,None,None,list_all=True):
        workload = query.data["workloads"][workload_id]

        if not workload["succeeded"]:
            continue

        history_data["workloads"][workload_id] = {
            "size": query.workload_size_id(workload_id),
            "pkg_count": len(query.workload_pkgs_id(workload_id)),
        }

    # Environments
    for env_id in query.envs(None,None,None,list_all=True):
        env = query.data["envs"][env_id]

        if not env["succeeded"]:
            continue

        history_data["envs"][env_id] = {
            "size": query.env_size_id(env_id),
            "pkg_count": len(query.env_pkgs_id(env_id)),
        }

    # Repositories
    for repo_id in query.configs["repos"].keys():
        history_data["repos"][repo_id] = {}

        for arch, pkgs in query.data["pkgs"][repo_id].items():
            history_data["repos"][repo_id][arch] = {
                "pkg_count": len(pkgs)
            }

    # Views (new)
    for view_conf_id, view_conf in query.configs["views"].items():
        view_all_arches = query.data["views_all_arches"][view_conf_id]

        view_data = {
            "srpm_count_env": view_all_arches["numbers"]["srpms"]["env"],
            "srpm_count_req": view_all_arches["numbers"]["srpms"]["req"],
            "srpm_count_dep": view_all_arches["numbers"]["srpms"]["dep"],
        }

        if view_all_arches["has_buildroot"]:
            view_data.update({
                "srpm_count_build_base": view_all_arches["numbers"]["srpms"]["build_base"],
                "srpm_count_build_level_1": view_all_arches["numbers"]["srpms"]["build_level_1"],
                "srpm_count_build_level_2_plus": view_all_arches["numbers"]["srpms"]["build_level_2_plus"],
            })

        history_data["views"][view_conf_id] = view_data

    # And save it
    log(f"  Saving in: {file_path}")
    dump_data(file_path, history_data)

    log("  Done!")
    log("")


def _read_historic_data(query):
    log("Reading historic data...")

    directory = os.path.join(query.settings["output"], "history")

    # Do some basic validation of the filename
    all_filenames = os.listdir(directory)
    pattern = re.compile(r'^historic_data-\d{4}-week_\d{3}\.json$')
    valid_filenames = sorted([
        filename for filename in all_filenames
        if pattern.match(filename)
    ])

    # Get the data
    historic_data = {}

    for filename in valid_filenames:
        with open(os.path.join(directory, filename), "r") as file:
            try:
                document = json.load(file)

                date = datetime.datetime.strptime(document["date"], "%Y-%m-%d")
                year = date.strftime("%Y")
                week = date.strftime("%W")
                key = f"{year}-week_{week}"
            except (KeyError, ValueError):
                err_log(f"Invalid file in historic data: {filename}. Ignoring.")
                continue

            historic_data[key] = document

    return historic_data


def _generate_chartjs_data(historic_data, query):

    # Data for workload pages
    for workload_id in query.workloads(None, None, None, None, list_all=True):

        entry_data = {
            # First, get the dates as chart labels
            "labels": [entry["date"] for entry in historic_data.values()],
            # Second, get the actual data for everything that's needed
            "datasets": []
        }

        workload = query.data["workloads"][workload_id]
        workload_conf_id = workload["workload_conf_id"]
        workload_conf = query.configs["workloads"][workload_conf_id]

        dataset = {
            "data": [],
            "label": workload_conf["name"],
            "fill": "false",
        }

        for _,entry in historic_data.items():
            try:
                size = entry["workloads"][workload_id]["size"]

                # The chart needs the size in MB, but just as a number
                size_mb = f"{size/1024/1024:.1f}"
                dataset["data"].append(size_mb)
            except KeyError:
                dataset["data"].append("null")

        entry_data["datasets"].append(dataset)

        entry_name = f"chartjs-data--workload--{workload_id}"
        _generate_json_file(entry_data, entry_name, query.settings)

    # Data for workload overview pages
    for workload_conf_id in query.workloads(None,None,None,None,output_change="workload_conf_ids"):
        for repo_id in query.workloads(workload_conf_id,None,None,None,output_change="repo_ids"):

            entry_data = {
                # First, get the dates as chart labels
                "labels": [entry["date"] for entry in historic_data.values()],
                # Second, get the actual data for everything that's needed
                "datasets": []
            }
            for workload_id in query.workloads(workload_conf_id, None, repo_id, None, list_all=True):

                workload = query.data["workloads"][workload_id]
                env_conf_id = workload["env_conf_id"]
                env_conf = query.configs["envs"][env_conf_id]

                dataset = {
                    "data": [],
                    "label": f"in {env_conf['name']} {workload['arch']}",
                    "fill": "false",
                }

                for _,entry in historic_data.items():
                    try:
                        size = entry["workloads"][workload_id]["size"]

                        # The chart needs the size in MB, but just as a number
                        size_mb = f"{size/1024/1024:.1f}"
                        dataset["data"].append(size_mb)
                    except KeyError:
                        dataset["data"].append("null")

                entry_data["datasets"].append(dataset)

            entry_name = f"chartjs-data--workload-overview--{workload_conf_id}--{repo_id}"
            _generate_json_file(entry_data, entry_name, query.settings)

    # Data for workload cmp arches pages
    for workload_conf_id in query.workloads(None,None,None,None,output_change="workload_conf_ids"):
        for env_conf_id in query.workloads(workload_conf_id,None,None,None,output_change="env_conf_ids"):
            for repo_id in query.workloads(workload_conf_id,env_conf_id,None,None,output_change="repo_ids"):

                workload_conf = query.configs["workloads"][workload_conf_id]
                env_conf = query.configs["envs"][env_conf_id]
                repo = query.configs["repos"][repo_id]

                entry_data = {
                    # First, get the dates as chart labels
                    "labels": [entry["date"] for entry in historic_data.values()],
                    # Second, get the actual data for everything that's needed
                    "datasets": []
                }

                for workload_id in query.workloads(workload_conf_id,env_conf_id,repo_id,None,list_all=True):

                    workload = query.data["workloads"][workload_id]
                    env_conf_id = workload["env_conf_id"]
                    env_conf = query.configs["envs"][env_conf_id]

                    dataset = {
                        "data": [],
                        "label": workload["arch"],
                        "fill": "false",
                    }

                    for _,entry in historic_data.items():
                        try:
                            size = entry["workloads"][workload_id]["size"]

                            # The chart needs the size in MB, but just as a number
                            size_mb = "{0:.1f}".format(size/1024/1024)
                            dataset["data"].append(size_mb)
                        except KeyError:
                            dataset["data"].append("null")

                    entry_data["datasets"].append(dataset)

                entry_name = f"chartjs-data--workload-cmp-arches--{workload_conf_id}--{env_conf_id}--{repo_id}"
                _generate_json_file(entry_data, entry_name, query.settings)

    # Data for workload cmp envs pages
    for workload_conf_id in query.workloads(None,None,None,None,output_change="workload_conf_ids"):
        for repo_id in query.workloads(workload_conf_id,None,None,None,output_change="repo_ids"):
            for arch in query.workloads(workload_conf_id,None,repo_id,None,output_change="arches"):

                workload_conf = query.configs["workloads"][workload_conf_id]
                env_conf = query.configs["envs"][env_conf_id]
                repo = query.configs["repos"][repo_id]

                entry_data = {
                    "labels": [entry["date"] for entry in historic_data.values()],
                    "datasets": []
                }

                for workload_id in query.workloads(workload_conf_id,None,repo_id,arch,list_all=True):

                    workload = query.data["workloads"][workload_id]
                    repo = query.configs["repos"][repo_id]

                    dataset = {
                        "data": [],
                        "label": f"{repo['name']} {workload['arch']}",
                        "fill": "false",
                    }

                    for _,entry in historic_data.items():
                        try:
                            size = entry["workloads"][workload_id]["size"]

                            # The chart needs the size in MB, but just as a number
                            size_mb = f"{size/1024/1024:.1f}"
                            dataset["data"].append(size_mb)
                        except KeyError:
                            dataset["data"].append("null")

                    entry_data["datasets"].append(dataset)

                entry_name = f"chartjs-data--workload-cmp-envs--{workload_conf_id}--{repo_id}--{arch}"
                _generate_json_file(entry_data, entry_name, query.settings)

    # Data for env pages
    for env_id in query.envs(None, None, None, list_all=True):

        entry_data = {
            "labels": [entry["date"] for entry in historic_data.values()],
            "datasets": []
        }

        env = query.data["envs"][env_id]
        env_conf_id = env["env_conf_id"]
        env_conf = query.configs["envs"][env_conf_id]

        dataset = {
            "data": [],
            "label": env_conf["name"],
            "fill": "false",
        }


        for _,entry in historic_data.items():
            try:
                size = entry["envs"][env_id]["size"]

                # The chart needs the size in MB, but just as a number
                size_mb = f"{size/1024/1024:.1f}"
                dataset["data"].append(size_mb)
            except KeyError:
                dataset["data"].append("null")

        entry_data["datasets"].append(dataset)

        entry_name = f"chartjs-data--env--{env_id}"
        _generate_json_file(entry_data, entry_name, query.settings)

    # Data for env overview pages
    for env_conf_id in query.envs(None,None,None,output_change="env_conf_ids"):
        for repo_id in query.envs(env_conf_id,None,None,output_change="repo_ids"):
            entry_data = {
                # First, get the dates as chart labels
                "labels": [entry["date"] for entry in historic_data.values()],
                # Second, get the actual data for everything that's needed
                "datasets": []
            }

            for env_id in query.envs(env_conf_id, repo_id, None, list_all=True):

                env = query.data["envs"][env_id]
                env_conf_id = env["env_conf_id"]
                env_conf = query.configs["envs"][env_conf_id]

                dataset = {
                    "data": [],
                    "label": f"in {env_conf['name']} {env['arch']}",
                    "fill": "false",
                }


                for _,entry in historic_data.items():
                    try:
                        size = entry["envs"][env_id]["size"]

                        # The chart needs the size in MB, but just as a number
                        size_mb = f"{size/1024/1024:.1f}"
                        dataset["data"].append(size_mb)
                    except KeyError:
                        dataset["data"].append("null")

                entry_data["datasets"].append(dataset)

            entry_name = f"chartjs-data--env-overview--{env_conf_id}--{repo_id}"
            _generate_json_file(entry_data, entry_name, query.settings)

    # Data for env cmp arches pages
    for env_conf_id in query.envs(None,None,None,output_change="env_conf_ids"):
        for repo_id in query.envs(env_conf_id,None,None,output_change="repo_ids"):

            env_conf = query.configs["envs"][env_conf_id]
            env_conf = query.configs["envs"][env_conf_id]
            repo = query.configs["repos"][repo_id]
            entry_data = {
                # First, get the dates as chart labels
                "labels": [entry["date"] for entry in historic_data.values()],
                # Second, get the actual data for everything that's needed
                "datasets": []
            }

            for env_id in query.envs(env_conf_id,repo_id,None,list_all=True):

                env = query.data["envs"][env_id]
                dataset = {
                    "data": [],
                    "label": env["arch"],
                    "fill": "false",
                }

                for _,entry in historic_data.items():
                    try:
                        size = entry["envs"][env_id]["size"]

                        # The chart needs the size in MB, but just as a number
                        size_mb = f"{size/1024/1024:.1f}"
                        dataset["data"].append(size_mb)
                    except KeyError:
                        dataset["data"].append("null")

                entry_data["datasets"].append(dataset)

            entry_name = "chartjs-data--env-cmp-arches--{env_conf_id}--{repo_id}".format(
                env_conf_id=env_conf_id,
                repo_id=repo_id
            )
            _generate_json_file(entry_data, entry_name, query.settings)

    # Data for view pages
    for view_conf_id in query.configs["views"].keys():
        view_all_arches = query.data["views_all_arches"][view_conf_id]

        entry_data = {
            # First, get the dates as chart labels
            "labels": [entry["date"] for entry in historic_data.values()],
            # Second, get the actual data for everything that's needed
            "datasets": []
        }

        dataset_names = ["env", "req", "dep"]
        if view_all_arches["has_buildroot"]:
            dataset_names.extend(["build_base", "build_level_1", "build_level_2_plus"])

        dataset_metadata = {
            "env": {
                "name": "Environment",
                "color": "#ffc107"
            },
            "req": {
                "name": "Required",
                "color": "#28a745"
            },
            "dep": {
                "name": "Dependency",
                "color": "#6c757d"
            },
            "build_base": {
                "name": "Base Buildroot",
                "color": "#a39e87"
            },
            "build_level_1": {
                "name": "Buildroot level 1",
                "color": "#999"
            },
            "build_level_2_plus": {
                "name": "Buildroot levels 2+",
                "color": "#bbb"
            },
        }

        for dataset_name in dataset_names:
            dataset_key = f"srpm_count_{dataset_name}"

            dataset = {
                "data": [],
                "label": dataset_metadata[dataset_name]["name"],
                "backgroundColor": dataset_metadata[dataset_name]["color"],
            }

            loop_index = 0
            for _,entry in historic_data.items():
                try:
                    srpm_count = entry["views"][view_conf_id][dataset_key]

                    # It's a stack chart, so I need to show the numbers on top of each other
                    srpm_count_compound = srpm_count if dataset_name == "env" else \
                        entry_data["datasets"][-1]["data"][loop_index] + srpm_count
                    dataset["data"].append(srpm_count_compound)
                except (KeyError, IndexError):
                    dataset["data"].append("null")

                loop_index += 1

            entry_data["datasets"].append(dataset)

        entry_name = "chartjs-data--view--{view_conf_id}".format(
            view_conf_id=view_conf_id
        )
        _generate_json_file(entry_data, entry_name, query.settings)


def generate_historic_data(query):
    log("")
    log("###############################################################################")
    log("### Historic Data #############################################################")
    log("###############################################################################")
    log("")

    # Step 1: Save current data
    _save_current_historic_data(query)

    # Step 2: Read historic data
    historic_data = _read_historic_data(query)

    # Step 3: Generate Chart.js data
    _generate_chartjs_data(historic_data, query)

    log("Done!")
    log("")
