#!/usr/bin/env python
# -*- coding: utf8 -*-
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
from jawa.util.descriptor import method_descriptor

from burger.util import WalkerCallback, walk_method

import six.moves

class BlocksTopping(Topping):
    """Gets most available block types."""

    PROVIDES = [
        "blocks"
    ]

    DEPENDS = [
        "identify.block.superclass",
        "identify.block.list",
        "identify.identifier",
        "language",
        "version.data",
        "version.is_flattened"
    ]

    @staticmethod
    def act(aggregate, classloader, verbose=False):
        if "data" in aggregate["version"] and aggregate["version"]["data"] >= 1461: # 18w02a
            BlocksTopping._process_1point13(aggregate, classloader, verbose)
        else:
            BlocksTopping._process_1point12(aggregate, classloader, verbose)

        # Shared logic: Go through the block list and add the field info.
        list = aggregate["classes"]["block.list"]
        lcf = classloader[list]

        blocks = aggregate["blocks"]
        block = blocks["block"]
        block_fields = blocks.setdefault("block_fields", {})

        # Find the static block, and load the fields for each.
        method = lcf.methods.find_one(name="<clinit>")
        blk_name = ""
        for ins in method.code.disassemble():
            if ins in ("ldc", "ldc_w"):
                const = ins.operands[0]
                if isinstance(const, String):
                    blk_name = const.string.value
            elif ins == "putstatic":
                if blk_name is None or blk_name == "Accessed Blocks before Bootstrap!":
                    continue
                const = ins.operands[0]
                field = const.name_and_type.name.value
                if blk_name in block:
                    block[blk_name]["field"] = field
                elif verbose:
                    print("Cannot find a block matching %s for field %s" % (blk_name, field))
                block_fields[field] = blk_name

    @staticmethod
    def _process_1point13(aggregate, classloader, verbose):
        # Handles versions after 1.13 (specifically >= 18w02a)
        superclass = aggregate["classes"]["block.superclass"]
        cf = classloader[superclass]
        block_list_name = aggregate["classes"]["block.list"]
        block_list = classloader[block_list_name]

        if "block" in aggregate["language"]:
            language = aggregate["language"]["block"]
        else:
            language = None

        # Figure out what the builder class is
        ctor = cf.methods.find_one(name="<init>")
        builder_class = ctor.args[0].name

        builder_cf = classloader[builder_class]
        # Sets hardness and resistance
        hardness_setter = builder_cf.methods.find_one(args='FF')
        # There's also one that sets both to the same value
        hardness_setter_2 = None
        for method in builder_cf.methods.find(args='F'):
            for ins in method.code.disassemble():
                if ins == "invokevirtual":
                    const = ins.operands[0]
                    if (const.name_and_type.name.value == hardness_setter.name.value and
                            const.name_and_type.descriptor.value == hardness_setter.descriptor.value):
                        hardness_setter_2 = method
                        break
        assert hardness_setter_2 != None
        # ... and one that sets them both to 0
        hardness_setter_3 = None
        for method in builder_cf.methods.find(args=''):
            for ins in method.code.disassemble():
                if ins == "invokevirtual":
                    const = ins.operands[0]
                    if (const.name_and_type.name.value == hardness_setter_2.name.value and
                            const.name_and_type.descriptor.value == hardness_setter_2.descriptor.value):
                        hardness_setter_3 = method
                        break
        assert hardness_setter_3 != None

        light_setter = builder_cf.methods.find_one(args='I')

        blocks = aggregate.setdefault("blocks", {})
        block = blocks.setdefault("block", {})
        ordered_blocks = blocks.setdefault("ordered_blocks", [])
        reflected_blocks = {}
        # Find the static block registration method
        method = block_list.methods.find_one(args='', returns="V", f=lambda m: m.access_flags.acc_static)

        class Walker(WalkerCallback):
            def __init__(self):
                self.cur_id = 0

            def on_new(self, ins, const):
                class_name = const.name.value
                return {"class": class_name}

            def on_invoke(self, ins, const, obj, args):
                method_name = const.name_and_type.name.value
                method_desc = const.name_and_type.descriptor.value
                desc = method_descriptor(method_desc)
                if ins == "invokestatic":
                    if const.class_.name == block_list_name:
                        # Call to the static register method.
                        text_id = args[0]
                        current_block = args[1]
                        current_block["text_id"] = text_id
                        current_block["numeric_id"] = self.cur_id
                        self.cur_id += 1
                        lang_key = "minecraft.%s" % text_id
                        if language != None and lang_key in language:
                            current_block["display_name"] = language[lang_key]
                        block[text_id] = current_block
                        ordered_blocks.append(text_id)
                        return text_id
                    elif const.class_.name == builder_class:
                        if desc.args[0].name == superclass: # Copy constructor
                            copy = dict(args[0])
                            del copy["text_id"]
                            del copy["numeric_id"]
                            del copy["class"]
                            if "display_name" in copy:
                                del copy["display_name"]
                            return copy
                        else:
                            return {} # Append current block
                else:
                    if method_name == "hasNext":
                        # We've reached the end of block registration
                        # (and have started iterating over registry keys)
                        raise StopIteration()

                    if method_name == hardness_setter.name and method_desc == hardness_setter.descriptor:
                        obj["hardness"] = args[0]
                        obj["resistance"] = args[1]
                    elif method_name == hardness_setter_2.name and method_desc == hardness_setter_2.descriptor:
                        obj["hardness"] = args[0]
                        obj["resistance"] = args[0]
                    elif method_name == hardness_setter_3.name and method_desc == hardness_setter_3.descriptor:
                        obj["hardness"] = 0.0
                        obj["resistance"] = 0.0
                    elif method_name == light_setter.name and method_desc == light_setter.descriptor:
                        obj["light"] = args[0]
                    elif method_name == "<init>":
                        # Call to the constructor for the block
                        # We can't hardcode index 0 because sand has an extra parameter, so use the last one
                        # There are also cases where it's an arg-less constructor; we don't want to do anything there.
                        if len(args) > 0:
                            obj.update(args[-1])

                    if desc.returns.name == builder_class:
                        return obj
                    elif desc.returns.name == aggregate["classes"]["identifier"]:
                        # Probably getting the air identifier from the registry
                        return "air"
                    elif desc.returns.name != "void":
                        return object()

            def on_get_field(self, ins, const, obj):
                if const.class_.name == superclass:
                    # Probably getting the static AIR resource location
                    return "air"
                elif const.class_.name == block_list_name: # clone
                    return block[reflected_blocks[const.name_and_type.name.value]]
                else:
                    return object()

            def on_put_field(self, ins, const, obj, value):
                if ins == "putstatic":
                    reflected_blocks[const.name_and_type.name.value] = value
                return

        walk_method(cf, method, Walker(), verbose)

    @staticmethod
    def _process_1point12(aggregate, classloader, verbose):
        # Handles versions prior to 1.13
        superclass = aggregate["classes"]["block.superclass"]
        cf = classloader[superclass]

        is_flattened = aggregate["version"]["is_flattened"]
        individual_textures = True #aggregate["version"]["protocol"] >= 52 # assume >1.5 http://wiki.vg/Protocol_History#1.5.x since don't read packets TODO

        if "tile" in aggregate["language"]:
            language = aggregate["language"]["tile"]
        elif "block" in aggregate["language"]:
            language = aggregate["language"]["block"]
        else:
            language = None

        # Find the static block registration method
        method = cf.methods.find_one(args='', returns="V", f=lambda m: m.access_flags.acc_public and m.access_flags.acc_static)

        blocks = aggregate.setdefault("blocks", {})
        block = blocks.setdefault("block", {})
        ordered_blocks = blocks.setdefault("ordered_blocks", [])
        tmp = []

        stack = []
        locals = {}
        for ins in method.code.disassemble():
            if ins == "new":
                # The beginning of a new block definition
                const = ins.operands[0]
                class_name = const.name.value
                current_block = {
                    "class": class_name,
                    "calls": {}
                }

                stack.append(current_block)
            elif ins.mnemonic.startswith("fconst"):
                stack.append(float(ins.mnemonic[-1]))
            elif ins == "aconst_null":
                stack.append(None)
            elif ins in ("bipush", "sipush"):
                stack.append(ins.operands[0].value)
            elif ins == "fdiv":
                den = stack.pop()
                num = stack.pop()
                if isinstance(den, (float, int)) and isinstance(num, dict) and "scale" in num:
                    num["scale"] /= den
                    stack.append(num)
                else:
                    stack.append({"numerator": num, "denominator": den})
            elif ins in ("ldc", "ldc_w"):
                const = ins.operands[0]

                if isinstance(const, ConstantClass):
                    stack.append("%s.class" % const.name.value)
                elif isinstance(const, String):
                    stack.append(const.string.value)
                else:
                    stack.append(const.value)
            elif ins == "getstatic":
                const = ins.operands[0]
                if const.class_.name == superclass:
                    # Probably getting the static AIR resource location
                    stack.append("air")
                else:
                    stack.append({"obj": None, "field": repr(const)})
            elif ins == "getfield":
                const = ins.operands[0]
                obj = stack.pop()
                if "text_id" in obj:
                    stack.append({
                        "block": obj["text_id"],
                        "field": const.name_and_type.name.value,
                        "scale": 1
                    })
                else:
                    stack.append({"obj": obj, "field": repr(const)})
            elif ins in ("invokevirtual", "invokespecial", "invokeinterface"):
                # A method invocation
                const = ins.operands[0]
                method_name = const.name_and_type.name.value
                method_desc = const.name_and_type.descriptor.value
                desc = method_descriptor(method_desc)
                num_args = len(desc.args)

                if method_name == "hasNext":
                    # We've reached the end of block registration
                    # (and have started iterating over registry keys)
                    break

                args = []
                for i in six.moves.range(num_args):
                    args.insert(0, stack.pop())
                obj = stack.pop()

                if "calls" in obj:
                    obj["calls"][method_name + method_desc] = args

                if desc.returns.name != "void":
                    if desc.returns.name == superclass:
                        stack.append(obj)
                    else:
                        stack.append({"obj": obj, "method": const, "args": args})
            elif ins == "invokestatic":
                # Call to the registration method
                const = ins.operands[0]
                desc = method_descriptor(const.name_and_type.descriptor.value)
                num_args = len(desc.args)

                if num_args == 3:
                    current_block = stack.pop()
                    current_block["text_id"] = stack.pop()
                    current_block["numeric_id"] = stack.pop()
                else:
                    assert num_args == 2
                    current_block = stack.pop()
                    current_block["text_id"] = stack.pop()

                tmp.append(current_block)
            elif ins == "astore":
                locals[ins.operands[0].value] = stack.pop()
            elif ins == "aload":
                stack.append(locals[ins.operands[0].value])
            elif ins == "dup":
                stack.append(stack[-1])
            elif ins == "checkcast":
                pass
            elif verbose:
                print("Unknown instruction %s: stack is %s" % (ins, stack))

        # Now that we have all of the blocks, we need a few more things
        # to make sense of what it all means. So,
        #   1. Find the function that returns 'this' and accepts a string.
        #      This is the name or texture setting function.
        #   2. Find the function that returns 'this' and accepts a float.
        #      This is the function that sets the hardness.

        string_setter = cf.methods.find_one(returns="L" + superclass + ";",
                args="Ljava/lang/String;",
                f=lambda x: not x.access_flags.acc_static)

        if string_setter:
            name_setter = string_setter.name.value + cf.constants.get(string_setter.descriptor.index).value
        else:
            name_setter = None

        float_setters = list(cf.methods.find(
            returns="L" + superclass + ";",
            args="F",
            f=lambda x: x.access_flags.acc_protected
        ))

        for method in float_setters:
            fld = None
            for ins in method.code.disassemble():
                if ins == "putfield":
                    const = ins.operands[0]
                    fld = const.name_and_type.name.value
                elif ins == "ifge":
                    hardness_setter = method.name.value + method.descriptor.value
                    hardness_field = fld
                    break

        for method in float_setters:
            # Look for the resistance setter, which multiplies by 3.
            is_resistance = False
            for ins in method.code.disassemble():
                if ins in ("ldc", "ldc_w"):
                    is_resistance = (ins.operands[0].value == 3.0)
                elif ins == "fmul" and is_resistance:
                    resistance_setter = method.name.value + method.descriptor.value
                elif ins == "putfield" and is_resistance:
                    const = ins.operands[0]
                    resistance_field = const.name_and_type.name.value
                    break
                else:
                    is_resistance = False

        for method in float_setters:
            # Look for the light setter, which multiplies by 15, but 15 is the first value (15 * val)
            is_light = False
            for ins in method.code.disassemble():
                if ins in ("ldc", "ldc_w"):
                    is_light = (ins.operands[0].value == 15.0)
                elif ins.mnemonic.startswith("fload"):
                    pass
                elif ins == "fmul" and is_light:
                    light_setter = method.name.value + method.descriptor.value
                    break
                else:
                    is_light = False

        if is_flattened:
            # Current IDs are incremental, manually track them
            cur_id = 0

        for blk in tmp:
            if not "text_id" in blk:
                if verbose:
                    print("Dropping nameless block:", blk)
                continue

            final = {}

            if "numeric_id" in blk:
                assert not is_flattened
                final["numeric_id"] = blk["numeric_id"]
            else:
                assert is_flattened
                final["numeric_id"] = cur_id
                cur_id += 1

            if "text_id" in blk:
                final["text_id"] = blk["text_id"]

            final["class"] = blk["class"]

            if name_setter in blk["calls"]:
                final["name"] = blk["calls"][name_setter][0]

            if "name" in final:
                lang_key = "%s.name" % final["name"]
            else:
                # 17w43a (1.13) and above - no specific translation string, only the id
                lang_key = "minecraft.%s" % final["text_id"]
            if language and lang_key in language:
                final["display_name"] = language[lang_key]

            if hardness_setter not in blk["calls"]:
                final["hardness"] = 0.0
                final["resistance"] = 0.0
            else:
                stack = blk["calls"][hardness_setter]
                if len(stack) == 0:
                    if verbose:
                        print("%s: Broken hardness value" % final["text_id"])
                    final["hardness"] = 0.0
                    final["resistance"] = 0.0
                else:
                    hardness = blk["calls"][hardness_setter][0]
                    if isinstance(hardness, dict) and "field" in hardness:
                        # Repair field info
                        assert hardness["field"] == hardness_field
                        assert "block" in hardness
                        assert hardness["block"] in block
                        hardness = block[hardness["block"]]["hardness"] * hardness["scale"]
                    final["hardness"] = hardness
                    # NOTE: vanilla multiples this value by 5, but then divides by 5 later
                    # Just ignore that multiplication to avoid confusion.
                    final["resistance"] = hardness

            if resistance_setter in blk["calls"]:
                resistance = blk["calls"][resistance_setter][0]
                if isinstance(resistance, dict) and "field" in resistance:
                    # Repair field info
                    assert resistance["field"] == resistance_field
                    assert "block" in resistance
                    assert resistance["block"] in block
                    resistance = block[resistance["block"]]["resistance"] * resistance["scale"]
                # The * 3 is also present in vanilla, strange logic
                # Division to normalize for the multiplication/division by 5.
                final["resistance"] = resistance * 3.0 / 5.0
            # Already set in the hardness area, so no need for an else clause

            if light_setter in blk["calls"]:
                final["light"] = int(blk["calls"][light_setter][0] * 15)

            ordered_blocks.append(final["text_id"])
            block[final["text_id"]] = final
