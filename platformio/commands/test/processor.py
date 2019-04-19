# Copyright (c) 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import atexit
from os import remove
from os.path import isdir, isfile, join
from string import Template

import click

from platformio import exception, util
from platformio.commands.run import cli as cmd_run
from platformio.commands.run import print_header

TRANSPORT_OPTIONS = {
    "arduino": {
        "include": "#include <Arduino.h>",
        "object": "",
        "putchar": "Serial.write(c)",
        "flush": "Serial.flush()",
        "begin": "Serial.begin($baudrate)",
        "end": "Serial.end()"
    },
    "mbed": {
        "include": "#include <mbed.h>",
        "object": "Serial pc(USBTX, USBRX);",
        "putchar": "pc.putc(c)",
        "flush": "",
        "begin": "pc.baud($baudrate)",
        "end": ""
    },
    "energia": {
        "include": "#include <Energia.h>",
        "object": "",
        "putchar": "Serial.write(c)",
        "flush": "Serial.flush()",
        "begin": "Serial.begin($baudrate)",
        "end": "Serial.end()"
    },
    "espidf": {
        "include": "#include <stdio.h>",
        "object": "",
        "putchar": "putchar(c)",
        "flush": "fflush(stdout)",
        "begin": "",
        "end": ""
    },
    "native": {
        "include": "#include <stdio.h>",
        "object": "",
        "putchar": "putchar(c)",
        "flush": "fflush(stdout)",
        "begin": "",
        "end": ""
    },
    "custom": {
        "include": '#include "unittest_transport.h"',
        "object": "",
        "putchar": "unittest_uart_putchar(c)",
        "flush": "unittest_uart_flush()",
        "begin": "unittest_uart_begin()",
        "end": "unittest_uart_end()"
    }
}


class TestProcessorBase(object):

    DEFAULT_BAUDRATE = 115200

    def __init__(self, cmd_ctx, testname, envname, options):
        self.cmd_ctx = cmd_ctx
        self.cmd_ctx.meta['piotest_processor'] = True
        self.test_name = testname
        self.options = options
        self.env_name = envname
        self.env_options = {
            k: v
            for k, v in options['project_config'].items("env:" + envname)
        }
        self._run_failed = False
        self._outputcpp_generated = False

    def get_transport(self):
        transport = self.env_options.get("framework")
        if self.env_options.get("platform") == "native":
            transport = "native"
        if "test_transport" in self.env_options:
            transport = self.env_options['test_transport']
        if transport not in TRANSPORT_OPTIONS:
            raise exception.PlatformioException(
                "Unknown Unit Test transport `%s`" % transport)
        return transport.lower()

    def get_baudrate(self):
        return int(self.env_options.get("test_speed", self.DEFAULT_BAUDRATE))

    def print_progress(self, text, is_error=False):
        click.echo()
        print_header(
            "[test/%s] %s" % (click.style(
                self.test_name, fg="yellow", bold=True), text),
            is_error=is_error)

    def build_or_upload(self, target):
        if not self._outputcpp_generated:
            self.generate_outputcpp(util.get_projecttest_dir())
            self._outputcpp_generated = True

        if self.test_name != "*":
            self.cmd_ctx.meta['piotest'] = self.test_name

        if not self.options['verbose']:
            click.echo("Please wait...")

        return self.cmd_ctx.invoke(
            cmd_run,
            project_dir=self.options['project_dir'],
            upload_port=self.options['upload_port'],
            silent=not self.options['verbose'],
            environment=[self.env_name],
            disable_auto_clean="nobuild" in target,
            target=target)

    def process(self):
        raise NotImplementedError

    def run(self):
        raise NotImplementedError

    def on_run_out(self, line):
        if line.endswith(":PASS"):
            click.echo(
                "%s\t[%s]" % (line[:-5], click.style("PASSED", fg="green")))
        elif ":FAIL" in line:
            self._run_failed = True
            click.echo("%s\t[%s]" % (line, click.style("FAILED", fg="red")))
        else:
            click.echo(line)

    def generate_outputcpp(self, test_dir):
        assert isdir(test_dir)

        cpp_tpl = "\n".join([
            "$include",
            "#include <output_export.h>",
            "",
            "$object",
            "",
            "void output_start(unsigned int baudrate)",
            "{",
            "    $begin;",
            "}",
            "",
            "void output_char(int c)",
            "{",
            "    $putchar;",
            "}",
            "",
            "void output_flush(void)",
            "{",
            "    $flush;",
            "}",
            "",
            "void output_complete(void)",
            "{",
            "   $end;",
            "}"
        ])  # yapf: disable

        def delete_tmptest_file(file_):
            try:
                remove(file_)
            except:  # pylint: disable=bare-except
                if isfile(file_):
                    click.secho(
                        "Warning: Could not remove temporary file '%s'. "
                        "Please remove it manually." % file_,
                        fg="yellow")

        tpl = Template(cpp_tpl).substitute(
            TRANSPORT_OPTIONS[self.get_transport()])
        data = Template(tpl).substitute(baudrate=self.get_baudrate())

        tmp_file = join(test_dir, "output_export.cpp")
        with open(tmp_file, "w") as f:
            f.write(data)

        atexit.register(delete_tmptest_file, tmp_file)
