"""
Copyright (c) 2011 Tyler Kenendy <tk@tkte.ch>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from .topping import Topping

from jawa.constants import *

import json

class VersionTopping(Topping):
    """Provides the protocol version."""

    PROVIDES = [
        "version.protocol",
        "version.name",
        "version.data",
        "version.is_flattened",
        "version.entity_format"
    ]

    DEPENDS = [
        "identify.nethandler.server",
        "identify.anvilchunkloader"
    ]

    @staticmethod
    def act(aggregate, classloader, verbose=False):
        versions = aggregate.setdefault("version", {})
        try:
            version_data=""
            with classloader.open("version.json") as jsonf:
                version_data = jsonf.read().decode("utf-8")
            version_json = json.loads(version_data)
            VersionTopping.load_version_json(aggregate, version_json)
        except FileNotFoundError:
            VersionTopping.get_protocol_version(aggregate, classloader, verbose)
            VersionTopping.get_data_version(aggregate, classloader, verbose)
        VersionTopping.get_entity_format(aggregate)

    # Example `json` from 1.14: {'id': '1.14 / 5dac5567e13e46bdb0c1d90aa8d8b3f7', 'name': '1.14', 'release_target': '1.14', 'world_version': 1952, 'protocol_version': 477, 'pack_version': 4, 'build_time': '2019-04-23T14:51:09+00:00', 'stable': False}

    @staticmethod
    def load_version_json(aggregate, json):
        versions = aggregate["version"]
        versions["protocol"] = json["protocol_version"]
        versions["name"] = json["name"]
        versions["data"] = json["world_version"]

    @staticmethod
    def get_protocol_version(aggregate, classloader, verbose):
        versions = aggregate["version"]
        if "nethandler.server" in aggregate["classes"]:
            nethandler = aggregate["classes"]["nethandler.server"]
            cf = classloader[nethandler]
            version = None
            looking_for_version_name = False
            for method in cf.methods:
                for instr in method.code.disassemble():
                    if instr in ("bipush", "sipush"):
                        version = instr.operands[0].value
                    elif instr == "ldc" and version is not None:
                        constant = instr.operands[0]
                        if isinstance(constant, String):
                            str = constant.string.value
                            if "multiplayer.disconnect.outdated_client" in str:
                                versions["protocol"] = version
                                looking_for_version_name = True
                                continue
                            elif looking_for_version_name:
                                versions["name"] = str
                                return
                            elif "Outdated server!" in str:
                                versions["protocol"] = version
                                versions["name"] = \
                                    str[len("Outdated server! I'm still on "):]
                                return
        elif verbose:
            print("Unable to determine protocol version")

    @staticmethod
    def get_data_version(aggregate, classloader, verbose):
        if "anvilchunkloader" in aggregate["classes"]:
            anvilchunkloader = aggregate["classes"]["anvilchunkloader"]
            cf = classloader[anvilchunkloader]

            for method in cf.methods:
                next_ins_is_version = False
                found_version = None
                for ins in method.code.disassemble():
                    if ins in ("ldc", "ldc_w"):
                        const = ins.operands[0]
                        if isinstance(const, String):
                            if const == "DataVersion":
                                next_ins_is_version = True
                            elif const == "hasLegacyStructureData":
                                # In 18w21a+, there are two places that reference DataVersion,
                                # one which is querying it and one which is saving it.
                                # We don't want the one that's querying it;
                                # if "hasLegacyStructureData" is present then we're in the
                                # querying one so break and try the next method
                                found_version = None
                                break
                        elif isinstance(const, Integer):
                            if next_ins_is_version:
                                found_version = const.value
                            break
                    elif not next_ins_is_version:
                        pass
                    elif ins in ("bipush", "sipush"):
                        found_version = ins.operands[0].value

                if found_version is not None:
                    aggregate["version"]["data"] = found_version
                    break
        elif verbose:
            print("Unable to determine data version")

    @staticmethod
    def get_entity_format(aggregate):
        if "data" in aggregate["version"]:
            data_version = aggregate["version"]["data"]
            # Versions after 17w46a (1449) are flattened
            aggregate["version"]["is_flattened"] = (data_version > 1449)
            if data_version >= 1461:
                # 1.13 (18w02a and above, 1461) uses yet another entity format
                aggregate["version"]["entity_format"] = "1.13"
            elif data_version >= 800:
                # 1.11 versions (16w32a and above, 800) use one entity format
                aggregate["version"]["entity_format"] = "1.11"
            else:
                # Old entity format
                aggregate["version"]["entity_format"] = "1.10"
        else:
            aggregate["version"]["is_flattened"] = False
            aggregate["version"]["entity_format"] = "1.10"
