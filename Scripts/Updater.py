import sys
import os
import time
import json
import KextBuilder
import tempfile
import subprocess
import shutil
import base64
import plistlib
import random

# Python-aware urllib stuff
if sys.version_info >= (3, 0):
    from urllib.request import urlopen
else:
    from urllib2 import urlopen

class Updater:

    def __init__(self):
        self.kb = KextBuilder.KextBuilder()
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        if not os.path.exists("plugins.json"):
            self.head("Missing Files!")
            print(" ")
            print("Plugins.json doesn't exist!\n\nExiting...")
            print(" ")
            os._exit(1)

        if not os.path.exists("/Applications/Xcode.app"):
            self.head("Xcode Missing!")
            print(" ")
            print("Xcode is not installed in your /Applications folder!\n\nExiting...")
            print(" ")
            os._exit(1)

        out = self._run_command("xcodebuild -checkFirstLaunchStatus", True)
        if not out[2] == 0:
            self.head("Xcode First Launch")
            print(" ")
            self._stream_output("sudo xcodebuild -runFirstLaunch", True)
            print(" ")
            print("If everything ran correctly please relaunch the script.\n")
            os._exit(1)

        self.h = 0
        self.w = 0
        self.hpad = 22
        self.wpad = 8

        self.ee = base64.b64decode("TG9vayBzYXVzZSEgIEFuIGVhc3RlciBlZ2ch".encode("utf-8")).decode("utf-8")
        self.es = base64.b64decode("c2F1c2U=".encode("utf-8")).decode("utf-8")

        self.sdk_path = "/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs"
        self.sdk_version_plist = "/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Info.plist"

        self.sdk_min_version = None
        if os.path.exists(self.sdk_version_plist):
            try:
                sdk_plist = plistlib.readPlist(self.sdk_version_plist)
                self.sdk_min_version = sdk_plist["MinimumSDKVersion"]
            except:
                pass
        if not self.sdk_min_version:
            cur_vers = self._get_output(["sw_vers", "-productVersion"])[0]
            self.sdk_min_version = ".".join(cur_vers.split(".")[:2])

        # Try to get our available SDKs
        self.sdk_list = self._get_sdk_list()

        self.xcode_opts = None
        self.sdk_over = None
        self.default_on_fail = False
        self.increment_sdk = False

        if os.path.exists("profiles.json"):
            self.profiles = json.load(open("profiles.json"))
        else:
            self.profiles = []
        self.selected_profile = None

        if os.path.exists("colors.json"):
            self.colors_dict = json.load(open("colors.json"))
        else:
            self.colors_dict = {}
        self.colors   = self.colors_dict.get("colors", [])
        self.hi_color = self.colors_dict.get("highlight", "")
        self.er_color = self.colors_dict.get("error", "")
        self.ch_color = self.colors_dict.get("changed", "")
        self.gd_color = self.colors_dict.get("success", "")
        self.rt_color = self.colors_dict.get("reset", "")

        # Order the colors quick
        if len(self.colors):
            reg = []
            bold = []
            for c in self.colors:
                if "bold" in c["name"].lower():
                    bold.append(c)
                else:
                    reg.append(c)
            reg.sort(key=lambda x: x["name"])
            bold.sort(key=lambda x: x["name"])
            reg.extend(bold)
            self.colors = reg

        self.version_url = "https://raw.githubusercontent.com/corpnewt/Lilu-And-Friends/master/Scripts/plugins.json"

        theJSON = json.load(open("plugins.json"))

        self.plugs = theJSON.get("Plugins", [])
        self.version = theJSON.get("Version", "0.0.0")
        self.checked_updates = False

        # Select default profile
        self._select_profile("default")


    # Helper methods
    def grab(self, prompt):
        if sys.version_info >= (3, 0):
            return input(prompt)
        else:
            return str(raw_input(prompt))

    def cprint(self, message, **kwargs):
        strip_colors = kwargs.get("strip_colors", False)
        reset = u"\u001b[0m"
        # Requires sys import
        for c in self.colors:
            if strip_colors:
                message = message.replace(c["find"], "")
            else:
                message = message.replace(c["find"], c["replace"])
        if strip_colors:
            return message
        sys.stdout.write(message)
        print(reset)

    def _stream_output(self, comm, shell = False):
        output = ""
        try:
            if shell and type(comm) is list:
                comm = " ".join(comm)
            if not shell and type(comm) is str:
                comm = comm.split()
            p = subprocess.Popen(comm, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)
            
            while True:
                cur = p.stdout.read(1)
                if(not cur):
                    break
                sys.stdout.write(cur)
                output += cur
                sys.stdout.flush()

            return output
        except:
            return output

    def _run_command(self, comm, shell = False):
        c = None
        try:
            if shell and type(comm) is list:
                comm = " ".join(comm)
            if not shell and type(comm) is str:
                comm = comm.split()
            p = subprocess.Popen(comm, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            c = p.communicate()
            return (c[0].decode("utf-8"), c[1].decode("utf-8"), p.returncode)
        except:
            if c == None:
                return ("", "Command not found!", 1)
            return (c[0].decode("utf-8"), c[1].decode("utf-8"), p.returncode)


    def _compare_versions(self, vers1, vers2):
        # Helper method to compare ##.## strings and determine
        # if vers1 is <= vers2
        #
        # vers1 < vers2 = True
        # vers1 = vers2 = None
        # vers1 > vers2 = False
        #
        try:
            v1_parts = vers1.split(".")
            v2_parts = vers2.split(".")
        except:
            # Formatted wrong - return None
            return None
        for i in range(len(v1_parts)):
            if int(v1_parts[i]) < int(v2_parts[i]):
                return True
            elif int(v1_parts[i]) > int(v2_parts[i]):
                return False
        # Never differed - return None, must be equal
        return None

    def _get_sdk_list(self, sdk_path = None):
        # Sets our sdk list with what's currently available
        avail_sdk = []
        if not sdk_path:
            sdk_path = self.sdk_path
        if os.path.exists(sdk_path):
            sdk_list = os.listdir(sdk_path)
            for sdk in sdk_list:
                # Organize them by name and version
                if sdk.lower() == "macosx.sdk":
                    # The default - so we're not sure what version
                    continue
                # Add some info
                new_entry = { 
                    "name"    : sdk,
                    "default" : False,
                    "version" : sdk.lower().replace("macosx", "").replace(".sdk", "")
                }
                try:
                    # This only works on aliases - so it'll fail for anything that's
                    # not linked to MacOSX.sdk
                    os.readlink(os.path.join(sdk_path, sdk))
                    new_entry["default"] = True
                except:
                    pass
                avail_sdk.append(new_entry)
        return avail_sdk

    def _have_sdk(self, sdk_vers):
        # First break it into ##.## format
        sdk_vers = sdk_vers.lower().replace("macosx", "").replace(".sdk", "")
        # Refresh our sdk list
        self.sdk_list = self._get_sdk_list()
        for sdk in self.sdk_list:
            if sdk["version"] == sdk_vers:
                return True
        return False

    def _can_use_sdk(self, sdk_vers):
        # First break it into ##.## format
        sdk_vers = sdk_vers.lower().replace("macosx", "").replace(".sdk", "")
        if not self._compare_versions(sdk_vers, self.sdk_min_version) == True:
            # sdk_verse is >= self.sdk_min_version
            return True
        return False

    def _get_sdk_for_vers(self, sdk_vers):
        # First break into ##.## format
        sdk_vers = sdk_vers.lower().replace("macosx", "").replace(".sdk", "")
        # Refresh our sdk list
        self.sdk_list = self._get_sdk_list()
        for sdk in self.sdk_list:
            if sdk["version"] == sdk_vers:
                return sdk
        return None

    def _increment_sdk(self, sdk_vers, amount = 1):
        # First break into ##.## format
        sdk_vers = sdk_vers.lower().replace("macosx", "").replace(".sdk", "")
        while True:
            sdk_list = sdk_vers.split(".")
            sdk_new  = sdk_list[0] + "." + str(int(sdk_list[1])+amount)
            if self._compare_versions(sdk_new, self._highest_sdk()['version']) == False:
                # We're past the highest
                return None
            # Check if we actually have this sdk
            full_sdk = self._get_sdk_for_vers(sdk_new)
            if full_sdk:
                return full_sdk
            sdk_vers = sdk_new
        return sdk_new

    def _highest_sdk(self):
        # Returns the highest sdk that we have
        self._get_sdk_list()
        highest_sdk = self.sdk_list[0]
        for sdk in self.sdk_list:
            if self._compare_versions(sdk["version"], highest_sdk["version"]) == False:
                # Got a higher version, set it
                highest_sdk = sdk
        return highest_sdk

    def _get_string(self, url):
        response = urlopen(url)
        CHUNK = 16 * 1024
        bytes_so_far = 0
        total_size = int(response.headers['Content-Length'])
        chunk_so_far = "".encode("utf-8")
        while True:
            chunk = response.read(CHUNK)
            bytes_so_far += len(chunk)
            #self._progress_hook(response, bytes_so_far, total_size)
            if not chunk:
                break
            chunk_so_far += chunk
        return chunk_so_far.decode("utf-8")

    def _progress_hook(self, response, bytes_so_far, total_size):
        percent = float(bytes_so_far) / total_size
        percent = round(percent*100, 2)
        sys.stdout.write("Downloaded {:,} of {:,} bytes ({:.2f}%)\r".format(bytes_so_far, total_size, percent))

    def _get_output(self, comm):
        try:
            p = subprocess.Popen(comm, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            c = p.communicate()
            return (c[0].decode("utf-8"), c[1].decode("utf-8"), p.returncode)
        except:
            return (c[0].decode("utf-8"), c[1].decode("utf-8"), p.returncode)

    def _get_git(self):
        # Returns the path to the git binary
        return self._get_output(["which", "git"])[0].split("\n")[0].split("\r")[0]

    # Header drawing method
    def head(self, text = "Lilu And Friends", width = 55):
        os.system("clear")
        print("  {}".format("#"*width))
        len_text = self.cprint(text, strip_colors=True)
        mid_len = int(round(width/2-len(len_text)/2)-2)
        middle = " #{}{}{}#".format(" "*mid_len, len_text, " "*((width - mid_len - len(len_text))-2))
        middle = middle.replace(len_text, text + self.rt_color) # always reset just in case
        self.cprint(middle)
        print("#"*width)

    def resize(self, width, height):
        print('\033[8;{};{}t'.format(height, width))

    def custom_quit(self):
        self.resize(self.w, self.h)
        self.head("Lilu And Friends v"+self.gd_color+self.version)
        print("by CorpNewt\n")
        print("Thanks for testing it out, for bugs/comments/complaints")
        print("send me a message on Reddit, or check out my GitHub:\n")
        print("www.reddit.com/u/corpnewt")
        print("www.github.com/corpnewt\n")
        print("Have a nice day/night!\n\n")
        os._exit(0)

    def profile(self):
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        self.head("Profiles")
        print(" ")
        if not len(self.profiles):
            self.cprint(self.er_color+"No profiles")
        else:
            ind = 0
            for option in self.profiles:
                ind += 1
                if self.selected_profile == option["Name"]:
                    pick = "[{}#{}]".format(self.ch_color, self.rt_color)
                else:
                    pick = "[ ]"
                extra = "1 kext " if len(option.get("Kexts", [])) == 1 else "{} kexts ".format(len(option.get("Kexts", [])))
                extra += "- Def build opts " if option.get("Xcode", None) == None else "- {}{}{}".format(self.ch_color, option.get("Xcode", None), self.rt_color)
                extra += "- Def sdk" if option.get("SDK", None) == None else "- {}{}{}".format(self.ch_color, option.get("SDK", None), self.rt_color)
                extra += " - {}DoF{}".format(self.ch_color, self.rt_color) if option.get("DefOnFail", False) else ""
                extra += " - {}iSDK{}".format(self.ch_color, self.rt_color) if option.get("IncrementSDK", False) else ""
                en = "{} {}. {}{}{} - {}".format(pick, ind, self.hi_color, option.get("Name", None), self.rt_color, extra)
                if len(self.cprint(en, strip_colors=True)) + self.wpad > self.w:
                    self.w = len(self.cprint(en, strip_colors=True)) + self.wpad
                self.cprint(en)
            self.resize(self.w, self.h)
        print(" ")
        print("S. Save Current Settings to Profile")
        print("R. Remove Selected Profile")
        print("N. Select None")
        print("M. Main Menu")
        print("Q. Quit")
        print(" ")
        menu = self.grab("Please make a selection:  ")

        if not len(menu):
            self.profile()
            return

        if menu[:1].lower() == "q":
            self.custom_quit()
        elif menu[:1].lower() == "m":
            return
        elif menu[:1].lower() == "n":
            for p in self.plugs:
                p["Picked"] = False
            self.selected_profile = None
            self.profile()
            return
        elif menu[:1].lower() == "r":
            # Remove the offending option
            for option in self.profiles:
                if option["Name"] == self.selected_profile:
                    self.profiles.remove(option)
                    break
            # Save to file
            json.dump(self.profiles, open("profiles.json", "w"), indent=2)
            self.selected_profile = None
            self.profile()
            return
        elif menu[:1].lower() == "s":
            self.save_profile()
            self.profile()
            return
        # Get numeric value
        try:
            menu = int(menu)
        except:
            # Not a number
            self.profile()
            return

        if menu > 0 and menu <= len(self.profiles):
            # Valid profile
            self._select_profile(self.profiles[menu-1]["Name"])
            self.profile()

    def _select_profile(self, profile_name):
        # Selects a profile by the passed name
        selected = None
        for pro in self.profiles:
            if pro["Name"].lower() == profile_name.lower():
                selected = pro
                break
        if not selected:
            return
        # Pick only the ones needed
        for p in self.plugs:
            p["Picked"] = True if p["Name"] in selected["Kexts"] else False
        # Set the rest of the options
        self.xcode_opts = selected.get("Xcode", None)
        self.selected_profile = selected.get("Name", None)
        self.sdk_over = selected.get("SDK", None)
        self.default_on_fail = selected.get("DefOnFail", False)
        self.increment_sdk = selected.get("IncrementSDK", False)
        
    def save_profile(self):
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        self.head("Save to Profile")
        print(" ")
        kextlist = []
        for option in self.plugs:
            if "Picked" in option and option["Picked"] == True:
                kextlist.append(option["Name"])
        if len(kextlist):
            info = "Selected Kexts ({}):\n\n{}{}{}\n\n".format(len(kextlist), self.hi_color, "{}, {}".format(self.rt_color, self.hi_color).join(kextlist), self.rt_color)
        else:
            info = "Selected Kexts (0):\n\n{}None{}\n\n".format(self.er_color, self.rt_color)
        if self.xcode_opts == None:
            info += "Xcodebuild Options:\n\nDefault\n\n"
        else:
            info += "Xcodebuild Options:\n\n{}{}{}\n\n".format(self.ch_color, self.xcode_opts, self.rt_color)
        if self.sdk_over == None:
            info += "SDK:\n\nDefault\n\n"
        else:
            info += "SDK:\n\n{}{}{}\n\n".format(self.ch_color, self.sdk_over, self.rt_color)
        info += "Defaults on Failure:\n\n{}{}{}\n\n".format(self.ch_color, self.default_on_fail, self.rt_color)
        info += "Increment SDK on Fail:\n\n{}{}{}\n\n".format(self.ch_color, self.increment_sdk, self.rt_color)
        info += "If a profile is named \"{}Default{}\" it will be loaded automatically\n\n".format(self.hi_color, self.rt_color)
        info += "P. Profile Menu\nM. Main Menu\nQ. Quit\n"
        self.cprint(info)
        menu = self.grab("Please type a name for your profile:  ")

        if not len(menu):
            self.save_profile()
            return
        
        if menu.lower() == "p":
            return
        elif menu.lower() == "q":
            self.custom_quit()
        elif menu.lower() == "m":
            self.main()
            return

        # We have a name
        for option in self.profiles:
            if option["Name"].lower() == menu.lower():
                # Updating
                option["Kexts"] = kextlist
                option["Xcode"] = self.xcode_opts
                option["SDK"] = self.sdk_over
                option["DefOnFail"] = self.default_on_fail
                option["IncrementSDK"] = self.increment_sdk
                # Save to file
                json.dump(self.profiles, open("profiles.json", "w"), indent=2)
                self.selected_profile = option["Name"]
                return
        # Didn't find it
        new_pro = { 
            "Name" : menu, 
            "Kexts" : kextlist, 
            "Xcode" : self.xcode_opts, 
            "SDK" : self.sdk_over, 
            "DefOnFail" : self.default_on_fail, 
            "IncrementSDK" : self. increment_sdk
            }
        self.profiles.append(new_pro)
        # Save to file
        json.dump(self.profiles, open("profiles.json", "w"), indent=2)
        self.selected_profile = menu

    def xcodeopts(self):
        self.resize(self.w, self.h)
        self.head("Xcode Options")
        print(" ")
        if not self.xcode_opts:
            print("Build Options: Default")
        else:
            print("Build Options: {}{}{}".format(self.ch_color, self.xcode_opts, self.rt_color))
        if not self.sdk_over:
            print("SDK Options:   Default")
        else:
            print("SDK Options:   {}{}{}".format(self.ch_color, self.sdk_over, self.rt_color))
        print(" ")
        print("C. Clear")
        print("M. Main Menu")
        print("S. SDK Override")
        print("Q. Quit")
        print(" ")
        menu = self.grab("Please type your build opts:  ")

        if not len(menu):
            self.xcodeopts()
            return
        if menu.lower() == "c":
            # Profile change!
            self.selected_profile = None
            self.xcode_opts = None
            self.xcodeopts()
            return
        if menu.lower() == "s":
            self.sdk_override()
            return
        elif menu.lower() == "m":
            return
        elif menu.lower() == "q":
            self.custom_quit()
        else:
            if not self.xcode_opts == menu:
                # Profile change!
                self.selected_profile = None
            self.xcode_opts = menu
        self.xcodeopts()

    def sdk_override(self):
        self.resize(self.w, self.h)
        self.head("SDK Overrides")
        print(" ")
        if not self.xcode_opts:
            print("Build Options: Default")
        else:
            print("Build Options: {}{}{}".format(self.ch_color, self.xcode_opts, self.rt_color))
        if not self.sdk_over:
            print("SDK Options:   Default")
        else:
            print("SDK Options:   {}{}{}".format(self.ch_color, self.sdk_over, self.rt_color))
        print(" ")
        print("C. Clear")
        print("X. Xcode Options")
        print("M. Main Menu")
        print("Q. Quit")
        print(" ")
        menu = self.grab("Please type your sdk override (macosx[##.##]):  ")

        if not len(menu):
            self.sdk_override()
            return
        if menu.lower() == "c":
            # Profile change!
            self.selected_profile = None
            self.sdk_over = None
            self.sdk_override()
            return
        elif menu.lower() == "x":
            self.xcodeopts()
            return
        elif menu.lower() == "m":
            self.main()
            return
        elif menu.lower() == "q":
            self.custom_quit()
        else:
            # Verify
            if not menu.lower().startswith("macosx"):
                # doesn't start with macosx - let's see if it fits the ##.## format
                try:
                    int_stuff = list(map(int, menu.split(".")))
                    if not len(int_stuff) == 2:
                        # Too many parts
                        self.sdk_override()
                        return
                    # set it to macosx##.## now
                    menu = "macosx" + menu
                except:
                    # not ##.## format - skip
                    self.sdk_override()
                    return

            # Got one - let's make sure we have it
            if not self._have_sdk(menu):
                self.head("Missing SDK!")
                print(" ")
                self.cprint(self.er_color+"You don't currently have a {} sdk.".format(menu))
                print("You can visit the following site to download more sdks:\n")
                print("https://github.com/phracker/MacOSX-SDKs")
                print(" ")
                self.grab("Press [enter] to continue...")
                self.sdk_override()
                return

            # We have it - let's make sure Xcode will use it
            if not self._can_use_sdk(menu):
                self.head("SDK Below Minimum!")
                print(" ")
                self.cprint(self.er_color+"Xcode is currently set to allow sdks of {} or higher.".format(self.sdk_min_version))
                print("You can edit the MinimumSDKVersion property in the Info.plist located at:\n")
                print(self.sdk_version_plist)
                print("\nto update this setting.")
                print(" ")
                self.grab("Press [enter] to continue...")
                self.sdk_override()
                return
            
            if not self.sdk_over == menu:
                # Profile change!
                self.selected_profile = None
            self.sdk_over = menu
        self.sdk_override()

    def need_update(self, new, curr):
        for i in range(len(curr)):
            if int(new[i]) < int(curr[i]):
                return False
            elif int(new[i]) > int(curr[i]):
                return True
        return False

    def check_update(self):
        # Checks against https://raw.githubusercontent.com/corpnewt/Lilu-And-Friends/master/Scripts/plugins.json to see if we need to update
        self.head("Checking for Updates")
        print(" ")
        try:
            newjson = self._get_string(self.version_url)
        except:
            # Not valid json data
            self.cprint(self.er_color+"Error checking for updates (network issue)")
            return
        try:
            newjson_dict = json.loads(newjson)
        except:
            # Not valid json data
            self.cprint(self.er_color+"Error checking for updates (json data malformed or non-existent)")
            return
        check_version = newjson_dict.get("Version", "0.0.0")
        changelist    = newjson_dict.get("Changes", None)
        if self.version == check_version:
            # The same - return
            self.cprint("v{}{}{} is already current.".format(self.gd_color, self.version, self.rt_color))
            return
        # Split the version number
        try:
            v = self.version.split(".")
            cv = check_version.split(".")
        except:
            # not formatted right - bail
            self.cprint(self.er_color+"Error checking for updates (version string malformed)")
            return

        if not self.need_update(cv, v):
            self.cprint("v{}{}{} is already current.".format(self.gd_color, self.version, self.rt_color))
            return
    
        # We need to update
        while True:
            if changelist:
                # We have changes to display
                msg = "v{}{}{} is available (v{}{}{} installed)\n\nWhat's New:\n\n{}{}{}\n".format(
                    self.gd_color, 
                    check_version,
                    self.rt_color,
                    self.gd_color, 
                    self.version,
                    self.rt_color,
                    self.ch_color, 
                    changelist,
                    self.rt_color
                    )
            else:
                msg = "v{}{}{} is available (v{}{}{} installed)\n".format(
                    self.gd_color, 
                    check_version,
                    self.rt_color,
                    self.gd_color,
                    self.version,
                    self.rt_color)
            self.cprint(msg)
            up = self.grab("Update? (y/n):  ")
            if up[:1].lower() in ["y", "n"]:
                break
        if up[:1].lower() == "n":
            print("Updating cancelled.")
            return
        # Update
        # Create temp folder
        t = tempfile.mkdtemp()
        g = self._get_git()
        # Clone into that folder
        os.chdir(t)
        output = self._get_output([g, "clone", "https://github.com/corpnewt/Lilu-and-Friends"])
        if not output[2] == 0:
            if os.path.exists(t):
                shutil.rmtree(t)
            print(output[1])
            os.chdir(os.path.dirname(os.path.realpath(__file__)))
            os.chdir("../")
            return
        # We've got the repo cloned
        # Move them over
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        os.chdir("../")
        p = subprocess.Popen("rsync -av \"" + t + "/Lilu-and-Friends/\" " + "\"" + os.getcwd() + "\"", shell=True)
        p.wait()
        p = subprocess.Popen("chmod +x \"" + os.getcwd() + "/Run.command\"", shell=True)
        p.wait()
        # Remove the old temp
        if os.path.exists(t):
            shutil.rmtree(t)
        self.head("Updated!")
        print(" ")
        print("Lilu and Friends has been updated!\nPlease restart the script to see the changes.")
        print(" ")
        self.grab("Press [enter] to quit...")
        exit(0)            

    def get_time(self, t):
        # A helper function to make a readable string between two times
        weeks   = int(t/604800)
        days    = int((t-(weeks*604800))/86400)
        hours   = int((t-(days*86400 + weeks*604800))/3600)
        minutes = int((t-(hours*3600 + days*86400 + weeks*604800))/60)
        seconds = int(t-(minutes*60 + hours*3600 + days*86400 + weeks*604800))
        msg = ""
        
        if weeks > 0:
            msg += "1 week, " if weeks == 1 else "{:,} weeks, ".format(weeks)
        if days > 0:
            msg += "1 day, " if days == 1 else "{:,} days, ".format(days)
        if hours > 0:
            msg += "1 hour, " if hours == 1 else "{:,} hours, ".format(hours)
        if minutes > 0:
            msg += "1 minute, " if minutes == 1 else "{:,} minutes, ".format(minutes)
        if seconds > 0:
            msg += "1 second, " if seconds == 1 else "{:,} seconds, ".format(seconds)

        if msg == "":
            return "0 seconds"
        else:
            return msg[:-2]

    def animate(self):
        self.head("Entirely Required")
        print(" ")
        pad = count = 0
        padmax = 29
        right = True
        while count <= 100:
            count += 1
            if right:
                pad += 1
                if pad > padmax:
                    right = False
            else:
                pad -= 1
                if pad < 0:
                    pad = 0
                    right = True
            sys.stdout.write(" "*pad + self.ee + "\r")
            time.sleep(.1)

    def pick_color(self, name, var):
        self.head("{}{} Color".format(var, name))
        print(" ")
        c = [ x for x in self.colors if x["replace"] != "\u001b[0m" ]
        for i in range(len(c)):
            self.cprint("{}. {}{}".format(i+1, c[i]["find"], c[i]["name"]))
        print(" ")
        print(" ")
        print("C. Color Picker")
        print("M. Main Menu")
        print("Q. Quit")
        print(" ")
        menu = self.grab("Please pick a new {} color:  ".format(name.lower()))

        if not len(menu):
            self.color_picker()
            return
        if menu[:1].lower() == "m":
            self.main()
            return
        elif menu[:1].lower() == "q":
            self.custom_quit()
        elif menu[:1].lower() == "c":
            return
        try:
            menu = int(menu)
        except:
            self.color_picker()
            return
        menu -= 1
        if menu < 0 or menu >= len(c):
            self.pick_color()
            return
        # Have a valid thing now
        var = c[menu]["find"]
        '''self.colors   = self.colors_dict.get("colors", [])
        self.hi_color = self.colors_dict.get("highlight", "")
        self.er_color = self.colors_dict.get("error", "")
        self.ch_color = self.colors_dict.get("changed", "")
        self.gd_color = self.colors_dict.get("success", "")
        self.rt_color = self.colors_dict.get("reset", "")'''
        self.colors_dict[name.lower()] = var
        if name.lower() == "highlight":
            self.hi_color = var
        elif name.lower() == "error":
            self.er_color = var
        elif name.lower() == "changed":
            self.ch_color = var
        elif name.lower() == "success":
            self.gd_color = var
        json.dump(self.colors_dict, open("colors.json", "w"), indent=2)

    def color_picker(self):
        c_list = [self.hi_color, self.ch_color, self.gd_color, self.er_color]
        n_list = ["Highlight", "Changed", "Success", "Error"]
        self.head("{}Color {}Picker".format(random.choice(c_list), random.choice(c_list)))
        print(" ")
        for i in range(len(c_list)):
            self.cprint("{}. {} {}Color".format(i+1, n_list[i], c_list[i]))
        print(" ")
        print("D. Reset to Defaults")
        print("M. Main Menu")
        print("Q. Quit")
        print(" ")
        menu = self.grab("Please pick a color to change:  ")

        if not len(menu):
            self.color_picker()
            return
        if menu[:1].lower() == "m":
            self.main()
            return
        elif menu[:1].lower() == "q":
            self.custom_quit()
        elif menu[:1].lower() == "d":
            self.hi_color = self.colors_dict["highlight"] = next((x["find"] for x in self.colors_dict["colors"] if x["find"] == "<bkb>"), "")
            self.er_color = self.colors_dict["error"]  = next((x["find"] for x in self.colors_dict["colors"] if x["find"] == "<rb>"), "")
            self.ch_color = self.colors_dict["changed"]  = next((x["find"] for x in self.colors_dict["colors"] if x["find"] == "<cb>"), "")
            self.gd_color = self.colors_dict["success"]  = next((x["find"] for x in self.colors_dict["colors"] if x["find"] == "<gb>"), "")
            json.dump(self.colors_dict, open("colors.json", "w"), indent=2)
        try:
            menu = int(menu)
        except:
            self.color_picker()
            return
        menu -= 1
        if menu < 0 or menu >= len(c_list):
            self.color_picker()
            return
        # Have a valid thing now
        self.pick_color(n_list[menu], c_list[menu])
        self.color_picker()
        return

    def main(self):
        if not self.checked_updates:
            self.check_update()
            self.checked_updates = True
        self.head("Lilu And Friends v"+self.gd_color+self.version)
        print(" ")
        # Print out options
        ind = 0
        for option in self.plugs:
            ind += 1
            if "Picked" in option and option["Picked"] == True:
                pick = "[{}#{}]".format(self.ch_color, self.rt_color)
            else:
                pick = "[ ]"
            if option.get("Desc", None):
                en = "{} {}. {}{}{} - {}".format(pick, ind, self.hi_color, option["Name"], self.rt_color, option["Desc"])
            else:
                en = "{} {}. {}{}{}".format(pick, ind, self.hi_color, option["Name"], self.rt_color)
            if len(self.cprint(en, strip_colors=True)) + self.wpad > self.w:
                self.w = len(self.cprint(en, strip_colors=True)) + self.wpad
            self.cprint(en)
        
        # Resize to fit
        self.h = self.hpad + len(self.plugs)
        self.resize(self.w, self.h)

        if not self.xcode_opts:
            print("Build Options:         Default")
        else:
            self.cprint("Build Options:         {}{}".format(self.ch_color, self.xcode_opts))
        if not self.sdk_over:
            print("SDK Options:           Default")
        else:
            self.cprint("SDK Options:           {}{}".format(self.ch_color, self.sdk_over))
        self.cprint("Increment SDK on Fail: {}{}".format(self.ch_color, self.increment_sdk))
        self.cprint("Defaults on Failure:   {}{}".format(self.ch_color, self.default_on_fail))

        print(" ")
        print("B. Build Selected")
        print(" ")
        print("A. Select All")
        print("N. Select None")
        print("X. Xcodebuild Options")
        print("P. Profiles")
        print("I. Increment SDK on Fail")
        print("F. Toggle Defaults on Failure")
        print("C. Color Picker")
        print("Q. Quit")
        print(" ")
        menu = self.grab("Please make a selection:  ")

        if not len(menu):
            return
        
        if menu[:1].lower() == "q":
            self.custom_quit()
        elif menu[:1].lower() == "f":
            # Profile change!
            self.selected_profile = None
            self.default_on_fail ^= True
        elif menu[:1].lower() == "i":
            # Profile change!
            self.selected_profile = None
            self.increment_sdk ^= True
        elif menu[:1].lower() == "x":
            self.xcodeopts()
        elif menu.lower() == self.es:
            self.animate()
        elif menu[:1].lower() == "p":
            self.profile()
        elif menu[:1].lower() == "c":
            self.color_picker()
        elif menu[:1].lower() == "b":
            # Building
            build_list = []
            for plug in self.plugs:
                if "Picked" in plug and plug["Picked"] == True:
                    # Initialize overrides
                    plug["xcode_opts"] = self.xcode_opts
                    plug["sdk_over"]   = self.sdk_over
                    plug["xcode_def_on_fail"] = False
                    plug["inc_sdk_on_fail"] = False
                    build_list.append(plug)
            if not len(build_list):
                self.head("WARNING")
                print(" ")
                print("Nothing to build - you must select at least one plugin!")
                time.sleep(3)
                return
            ind = 0
            success = []
            fail    = []
            # Take time
            start_time = time.time()
            total_kexts = len(build_list)
            self.head("Building 1 kext") if len(build_list) == 1 else self.head("Building {} kexts".format(len(build_list)))
            while len(build_list):
                plug = build_list.pop(0)
                ind += 1
                try:
                    out = self.kb.build(plug, ind, total_kexts, plug["xcode_opts"], plug["sdk_over"])
                except Exception as e:
                    print(e)
                    out = ["", "An error occurred!", 1]
                success_string = ""
                if out in [ None, True ]:
                    # Format our output
                    if out == None:
                        success_string += "    " + self.hi_color + plug["Name"] + self.rt_color
                    elif out == True:
                        success_string += "    " + self.hi_color + plug["Name"] + self.rt_color + " - " + self.er_color + "Errored, use with caution" + self.rt_color
                    if plug["inc_sdk_on_fail"]:
                        success_string += " - {}{} SDK{}".format(self.ch_color, plug["sdk_over"].lower().replace("macosx", "").replace(".sdk", ""), self.rt_color)
                    if plug["xcode_def_on_fail"]:
                        success_string += " - {}Xcode and SDK defaults{}".format(self.ch_color, self.rt_color)
                    success.append(success_string)
                else:
                    self.cprint(self.er_color + out[1])
                    if self.increment_sdk:
                        if plug["sdk_over"]:
                            new_sdk = self._increment_sdk(plug["sdk_over"])
                            if new_sdk:
                                self.cprint("\n{}Retrying {} with {} SDK.  Appended to end of list.\n".format(self.ch_color, plug["Name"], new_sdk['version']))
                                plug["sdk_over"] = "macosx" + new_sdk['version']
                                plug["inc_sdk_on_fail"] = True
                                build_list.append(plug)
                                # Back up the index
                                ind -= 1
                                continue
                    if self.default_on_fail:
                        if plug["sdk_over"] or plug["xcode_opts"]:
                            self.cprint("\n{}Retrying {} with Xcode and SDK defaults.  Appended to end of list.\n".format(self.ch_color, plug["Name"]))
                            plug["sdk_over"]   = None
                            plug["xcode_opts"] = None
                            plug["xcode_def_on_fail"] = True
                            # Reset sdk increment
                            plug["inc_sdk_on_fail"] = False
                            build_list.append(plug)
                            # Back up the index
                            ind -=1
                            continue
                    fail.append("    " + plug["Name"])
            # Clean up temp
            print("Cleaning up...")
            self.kb._del_temp()
            # Take time
            total_time = time.time() - start_time
            self.head("{} of {} Succeeded".format(len(success), total_kexts))
            print(" ")
            if len(success):
                self.cprint("{}Succeeded:{}\n\n{}".format(self.hi_color, self.rt_color, "\n".join(success)))
                try:
                    # Attempt to locate and open the kexts directory
                    os.chdir(os.path.dirname(os.path.realpath(__file__)))
                    os.chdir("../Kexts")
                    subprocess.Popen("open \"" + os.getcwd() + "\"", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                except:
                    pass
            else:
                self.cprint("{}Succeeded:{}\n\n    {}None".format(self.hi_color, self.rt_color, self.er_color))
            if len(fail):
                self.cprint("\n{}Failed:{}\n\n{}{}".format(self.hi_color, self.rt_color, self.er_color, "\n".join(fail)))
            else:
                self.cprint("\n{}Failed:{}\n\n    {}None".format(self.hi_color, self.rt_color, self.gd_color))
            print(" ")
            s = "second" if total_time == 1 else "seconds"
            print("Build took {}.\n".format(self.get_time(total_time)))
            self.grab("Press [enter] to return to the main menu...")
            return
                
        elif menu[:1].lower() == "a":
            # Select all
            for plug in self.plugs:
                plug["Picked"] = True
            # Profile change!
            self.selected_profile = None
            return
        elif menu[:1].lower() == "n":
            # Select none
            for plug in self.plugs:
                plug["Picked"] = False
            # Profile change!
            self.selected_profile = None
            return
        
        # First try to split
        menu = menu.replace(" ", "")
        menu_list = menu.split(",")
        for m in menu_list:
            # Get numeric value
            try:
                m = int(m)
            except:
                continue
            if m > 0 and m <= len(self.plugs):
                # Remove profile selection - as we've made changes
                self.selected_profile = None
                m -=1
                if "Picked" in self.plugs[m]:
                    if self.plugs[m]["Picked"]:
                        self.plugs[m]["Picked"] = False
                        continue
                self.plugs[m]["Picked"] = True
        return

# Create our main class, and loop - catching exceptions
up = Updater()
while True:
    try:
        up.main()
    except Exception as e:
        print(e)
        time.sleep(5)
