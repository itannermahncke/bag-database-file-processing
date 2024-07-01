"""
Contains functions relevant to the process of naming, tagging and uploading
bag files into the Acomms bag database.
"""

import re  # find CSRF token
import time  # add universal date/time tags (use datetime instead?)
from datetime import datetime  # timestamps in log file
from argparse import ArgumentParser  # configure script with args
from pathlib import Path  # file directory and name control
from rosbag import Bag  # interact with bag files
from std_msgs.msg import String  # create a String message to publish
from genpy import Time  # avoid disruptive message timestamps
from bs4 import BeautifulSoup  # find CSRF token
from requests_toolbelt import MultipartEncoder  # file upload in post request
from requests import Session  # post repeatedly without loss of authentication


# configuration from command-line args
parser = ArgumentParser()
parser.add_argument(
    "-q",
    "--quiet",
    nargs="?",
    const=True,  # if flag provided, do not print to console
    default=False,  # if nothing provided, print to console
    help="option to avoid printing to console (True/False)",
)
parser.add_argument(
    "-r",
    "--recursive",
    nargs="?",
    const=True,  # if '-r' flag provided, run recursively
    default=False,  # if nothing provided, run nonrecursively
    help="option to search for bags recursively (True/False).",
)
parser.add_argument(
    "-u",
    "--url",
    nargs="?",
    default="http://128.128.231.113:8080",  # if nothing provided, go here
    help="option to specify the database web url.",
)
args = vars(parser.parse_args())

IS_QUIET = args["quiet"]
IS_RECURSIVE = args["recursive"]
URL = args["url"]


# hard-coded Acomms vehicle information
vehicle_info = {
    "remus": (
        "ros_remus/Status",
        (
            "shadow",
            "casper",
            "bullwinkle",
        ),
    ),
    "buoy": (
        "ros_gwb/ScheduleStatus",
        (
            "sugar",
            "skipper",
            "shrew",
        ),
    ),
    # vehicle_type: (unique_message_type, (list, of, vehicles)),
}


# the following three functions are miscellanous quality-of-life functions.
def log(txt: str):
    """
    Option to write to logfile rather than printing to console.

    Args:
        txt (str): Text to write to logfile.
    """
    with open("log.txt", "a", encoding="utf-8") as f:
        f.write(f"\n{datetime.now()} : {txt}")
    if not IS_QUIET:
        print(txt)


def get_csrf_token(s: Session):
    """
    Gets a CSRF token generated by the database for the current session.

    Args:
        s (Session, optional): The current session for requests.

    Returns:
        string: A CSRF token for the given session.
    """
    log("Retrieving CSRF token.")
    html = s.get(URL).text
    log("Got html")
    soup = BeautifulSoup(html, "lxml")
    csrf = None
    log("Finding string with token")
    script_items = soup.find(string=re.compile("csrfToken")).split(";")
    log("Found")
    for i, string in enumerate(script_items):
        log(f"Step {i} of {len(script_items) - 1}")
        if "csrfToken" in string:
            csrf = string[string.find('"') + 1 : len(string) - 1]
    log(f"Token: {csrf}")
    return csrf


def identify_date(bag: Bag):
    """
    Finds the date and time that the bag file started recording and returns
    it in a format that is useful for including in a filename.

    Args:
        bag (Path): The bag to find the start date/time of.

    Returns:
        str: The date and time that the bag file started recording, in the
        following format: year-month-day-hour-minute-second
    """
    date = ""
    for i, val in enumerate(time.localtime(bag.get_start_time())):
        date += f"{val}-"
        if i == 6:  # don't log beyond seconds or things get weird
            break
    return date.rstrip("-")


# the following three functions are related to determining the quality of a
# bag's filename and potentially attempting a rename.
def is_rename_necessary(filename: str):
    """
    Evaluate whether or not the bag file has a "valid" filename, i.e. a
    filename that can be parsed correctly by the bag upload script. Correct
    name format: (vehicletype)_(vehiclename)_(msn_)datetime.bag

    Args:
        filename (str): The name of the bag file to evaluate.

    Returns:
        bool: True if the bag file must be renamed; False if not.
    """
    # correct name example: remus_shadow_(msn_)datetime.bag
    components = filename.split("_")
    if 2 < len(components) and len(components) < 5:  # correct component number
        if components[0] in vehicle_info:  # valid type
            if components[1] in vehicle_info[components[0]][1]:  # valid name

                log(f"---Bag {filename} has a valid name; skipping to next file.")
                return False
    log(f"--Bag {filename} has an invalid name; renaming now.")
    return True


def identify_source(bag: Path):
    """
    Attempts to find information about the bag file's source vehicle.

    Args:
        bag (Path): The bag file to identify the source of.

    Returns:
        source (str): The source vehicle information in the format of
        "vehicletype_vehiclename".
        status (int): An integer code representing the method used to identify
        the source: 0 is a failure, 1 used the parent directories, and 2 used
        the bag contents.
    """
    status = 0
    # search parent directories for a vehicle name
    log(f"---Attempting to rename {bag.name} by directory.")
    for parent_folder in bag.parts:
        for v_type, v_info in vehicle_info.items():
            if parent_folder in v_info[1]:
                source = f"{v_type}_{parent_folder}"
                status = 1
    # if directory strategy fails, attempt by contents
    if not bool(status):
        log("---Directory naming failed; attempting to name by contents.")
        msg_types = Bag(bag, "r").get_type_and_topic_info()._asdict()["msg_types"]
        for v_type, v_info in vehicle_info.items():
            if v_info[0] in msg_types:
                source = f"{v_type}_unknownname"
                status = 2
    # if contents strategy fails, give up
    if not bool(status):
        log("---Content naming failed.")
        source = "unknowntype_unknownname"
    # return whatever information could be found
    return source, status


def standard_rename(bag: Path):
    """
    Examines the name of a bag file and determines whether it must be renamed.
    If so, use the parent directories and/or the contents of the bag file to
    rename it.

    Args:
        bag (Path): The bag to evaluate and potentially rename.

    Returns:
        bool: True if the file is safe to tag and upload to the database; False
        if not.
        Path: The path to the renamed file. This is because once the file has
        been renamed, the original path is meaningless.
    """
    to_upload = True
    newpath = bag
    log(f"-Evaluating filename {bag.name}")
    # evaluate if bag should be renamed
    if is_rename_necessary(bag.name):
        # create a new name for the file
        source, status = identify_source(bag)
        built_name = f"{source}_{identify_date(Bag(bag))}.bag"
        # print out a status message based on the quality of the name
        if status == 0:
            log(
                f"--Could not retrieve vehicle info, named bag {built_name}. "
                + "Do not upload this bag file to the database until its "
                + "source vehicle can be identified."
            )
            to_upload = False
        elif status == 1:
            log(f"--Retrieved good name info {built_name} from directory.")
        elif status == 2:
            log(
                f"--Retrieved name info {built_name} from contents. The "
                + "invididual vehicle could not be identified, please add "
                + "the source vehicle's name to the filename manually "
                + "before uploading this file to the database."
            )
            to_upload = False
        # rename the bag file
        newpath = Path(bag.parent / built_name)
        bag.rename(newpath)
    log("-Finished evaluation.")
    return to_upload, newpath


# the following three functions are related to tagging and uploading a file
# who has passed all of its inspections to the database.
def generate_tags(bag: Bag):
    """
    Given a bag file, identify all relevant tags using the contents of the file
    and return them in a dictionary.

    Args:
        bag (Bag): The bag file to be tagged.

    Returns:
        dict: A dictionary of tags to be published as metadata.
    """
    bagname = str(bag.filename).rsplit("/", 1)[1]
    log(f"-Attempting to tag {bagname}")

    # establish variables for tagging
    bag_name_list = bagname.split("_")
    tags = {}

    # set universally possessed tags
    tags["vehicle"] = bag_name_list[0]
    tags["name"] = bag_name_list[1]
    tags["date/time"] = identify_date(bag)
    tags["year"] = tags["date/time"][:4]

    # set vehicle type-specific tags
    if tags["vehicle"] == "remus":  # for remus
        depth_list = []
        mission_modes = []
        # mission status (assuming it doesn't change)
        for _, msg, _ in bag.read_messages(topics="/status"):
            tags["mission state"] = msg.in_mission
            break
        # max depth and mission mode
        for _, msg, _ in bag.read_messages(topics="/status"):
            depth_list.append(round(float(msg.depth), 2))
            mission_modes.append(msg.mission_mode)
        tags["max depth"] = max(depth_list)
        tags["mission modes"] = set(mission_modes)
    elif tags["vehicle"] == "buoy":  # for buoy
        pass
    # elif bag_attributes["v_type"] == "your_vehicle_here":

    return tags


def tag_this_bag(bag: Bag, tags: dict):
    """
    Given a bag file and a dictionary of tags, publish the tags to the bag
    file's metadata topic.

    Args:
        bag (Bag): The bag file to be tagged.
        tags (dict): The tags to publish to the bag file's metadata.
    """
    # convert tag dictionary into standard string message
    tag_msg = String(data="")
    for key, val in tags.items():
        tag_msg.data += f"{key}:{val}\n"
    tag_msg.data = tag_msg.data.rstrip()

    # publish message to bag metadata topic without disruptive timestamp
    log(f"--Publishing message with data: \n{tag_msg.data}")
    msg_sec, msg_nsec = divmod(bag.get_end_time(), 1)
    bag.write("/metadata", tag_msg, Time(int(msg_sec), msg_nsec))
    log("--Successfully tagged bag.")


def prep_and_post(filepath: Path, s: Session, csrf: str):
    """
    Given a path to a tagged bag file, perform a post request to the database
    with the prepared bag file.

    Args:
        filepath (Path): The path to the tagged bag file.
        s (Session): The current session.
        csrf (str): A CSRF token for the current session.

    Returns:
        str: The status code returned by the post request.
    """
    # assemble data
    file_upload = MultipartEncoder(
        fields={
            "targetDirectory": ".",  # str of path
            "storageId": "default",
            "_csrf": csrf,
            "file": (
                filepath.name,
                open(filepath, "rb"),  # pylint: disable=consider-using-with
                "application/octet-stream",
            ),
        }
    )

    # attempt post to database
    r = s.post(
        URL + "/bags/upload",
        file_upload,
        headers={"Content-Type": file_upload.content_type},
    )

    return str(r.status_code)


# the following function is the central function of the file.
def process_bags():
    """
    Loop through each bag file in the directory (optionally recursive) and
    attempt to upload it to the bag database with relevant tags in its
    metadata.

    The function will refuse to upload any bags that do not follow the correct
    naming convention, but it will attempt to rename those files first.

    The uploaded files will be moved to an "uploaded folder", while files that
    could not be uploaded will remain in their original directory.
    """
    # some paths
    thisdir = Path.cwd()
    post_folder = "uploaded"

    # other useful variables
    bagfiles = list(thisdir.glob({True: "**/*.bag", False: "*.bag"}[IS_RECURSIVE]))

    # activate session
    with Session() as sesh:
        # retrieve a CSRF token for this session
        csrf = get_csrf_token(sesh)

        # tag and post each bag in the directory, counting each time
        i = 1
        net = len(bagfiles)
        for bagpath in bagfiles:
            log(f"Processing bag {bagpath.name} ({i}/{net})")
            i += 1
            # avoid bags that have already been uploaded
            if bagpath.parts[-1] != post_folder:  # irrelevant when nonrecursive
                # if bag has a good filename, or was renamed adequately
                rename_results, bagpath = standard_rename(bagpath)
                if rename_results:
                    # create a bag file and attempt to tag it
                    bag = Bag(bagpath, mode="a")
                    try:  # catch exceptions to avoid having to reindex an open bag
                        tags = generate_tags(bag)
                        tag_this_bag(bag, tags)
                        bag.close()
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        log(f"Error {e}.\nClosing and skipping bag without upload.")
                        bag.close()
                        continue

                    # assemble the multipart data
                    post_status = prep_and_post(bagpath, sesh, csrf)
                    if post_status == "200":
                        log("Successful file upload. Moving file to subdirectory.")
                        Path(bagpath.parent / post_folder).mkdir(exist_ok=True)
                        bagpath.rename(bagpath.parent / post_folder / bagpath.name)
                    else:
                        log(f"Post request failed with status code {post_status}.")
                else:
                    log(
                        f"Bag {bagpath.name} does not have enough metadata "
                        + "to be uploaded safely. Skipping bag without upload."
                    )
            else:
                log(f"Ignoring pre-existing bag {bagpath.name} in '{bagpath.parent}'")


if __name__ == "__main__":
    log("**Processing new bag file batch.**")
    process_bags()
    log("**Finished processing.**")
