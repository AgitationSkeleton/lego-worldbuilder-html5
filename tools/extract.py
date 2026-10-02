"""First step of the build: unprotect and decompile the two Shockwave movies.

    python tools/extract.py <folder with worldbuilder.dcr and worldbuilder2.dcr>

Runs ProjectorRays (https://github.com/ProjectorRays/ProjectorRays, 0.2.0 or later) on each
movie, which writes an unprotected .dir and the movie's Lingo as text to work/pr/.  The
.dcr files can sit anywhere under the folder given.

It also builds work/tools/pfr1json, a small program that reads the fonts the movies embed
(Director's PFR1 format) with LibreShockwave's parser
(https://github.com/Quackster/LibreShockwave, AGPL-3.0; fetched to work/, not part of
this repository) and writes their outlines as JSON for tools/build_library.py.

Set PROJECTORRAYS to the ProjectorRays executable if it is not on the PATH, and CXX to a
C++20 compiler if neither clang++ nor g++ is.
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, 'work')
MOVIES = ['worldbuilder', 'worldbuilder2']
LIBRESHOCKWAVE = 'https://github.com/Quackster/LibreShockwave.git'
LIBRESHOCKWAVE_COMMIT = 'fca530f9ef388d7ff38fa6c7117feae5bb5411c6'

PFR1JSON = r'''// Dump a PFR1 font (Director's embedded font format), as LibreShockwave parses it, to JSON.
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>
#include "libreshockwave/font/Pfr1Font.hpp"
using namespace libreshockwave::font;
int main(int argc, char **argv) {
    if (argc < 3) return 2;
    std::ifstream in(argv[1], std::ios::binary);
    std::vector<std::uint8_t> data((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    auto f = Pfr1Font::parse(data);
    if (!f) { std::fprintf(stderr, "parse failed\n"); return 1; }
    FILE *o = std::fopen(argv[2], "w");
    auto &m = f->metrics;
    std::fprintf(o, "{\"name\":\"%s\",\"outlineResolution\":%d,\"metricsResolution\":%d,\"bbox\":[%d,%d,%d,%d],\"ascender\":%d,\"descender\":%d,\"glyphs\":[",
        f->fontName.c_str(), m.outlineResolution, m.metricsResolution, m.xMin, m.yMin, m.xMax, m.yMax, m.ascender, m.descender);
    bool first = true;
    for (auto &rec : f->charRecords) {
        auto it = f->glyphs.find(rec.charCode);
        std::fprintf(o, "%s{\"code\":%d,\"setWidth\":%d,\"contours\":[", first ? "" : ",", rec.charCode, rec.setWidth);
        first = false;
        if (it != f->glyphs.end()) {
            bool fc = true;
            for (auto &c : it->second.contours) {
                std::fprintf(o, "%s[", fc ? "" : ","); fc = false;
                bool fm = true;
                for (auto &cmd : c.commands) {
                    std::fprintf(o, "%s[%d,%g,%g,%g,%g,%g,%g]", fm ? "" : ",", cmd.type, cmd.x, cmd.y, cmd.x1, cmd.y1, cmd.x2, cmd.y2);
                    fm = false;
                }
                std::fprintf(o, "]");
            }
        }
        std::fprintf(o, "]}");
    }
    std::fprintf(o, "]}\n");
    std::fclose(o);
    return 0;
}
'''


def find_movie(folder, name):
    for dirpath, _, files in os.walk(folder):
        for f in files:
            if f.lower() == name + '.dcr':
                return os.path.join(dirpath, f)
    raise SystemExit('could not find %s.dcr under %s' % (name, folder))


def decompile(folder):
    pr = os.environ.get('PROJECTORRAYS') or shutil.which('projectorrays') or shutil.which('projectorrays-0.2.0')
    if not pr:
        raise SystemExit('ProjectorRays not found: set PROJECTORRAYS')
    for name in MOVIES:
        src = find_movie(folder, name)
        out = os.path.join(WORK, 'pr', name)
        os.makedirs(out, exist_ok=True)
        local = os.path.join(WORK, 'pr', name + '.dcr')
        shutil.copyfile(src, local)
        subprocess.run([pr, 'decompile', local, '-o', out, '--dump-scripts'], check=True)


def build_pfr1json():
    tools = os.path.join(WORK, 'tools')
    exe = os.path.join(tools, 'pfr1json.exe' if os.name == 'nt' else 'pfr1json')
    if os.path.exists(exe):
        return
    os.makedirs(tools, exist_ok=True)
    src = os.path.join(WORK, 'LibreShockwave')
    if not os.path.exists(src):
        subprocess.run(['git', 'clone', LIBRESHOCKWAVE, src], check=True)
    subprocess.run(['git', '-C', src, 'checkout', '-q', LIBRESHOCKWAVE_COMMIT], check=True)
    main = os.path.join(tools, 'pfr1json.cpp')
    open(main, 'w').write(PFR1JSON)
    cxx = os.environ.get('CXX') or shutil.which('clang++') or shutil.which('g++')
    if not cxx:
        raise SystemExit('no C++ compiler found: set CXX')
    lib = os.path.join(src, 'cpp')
    subprocess.run([cxx, '-std=c++20', '-O2', '-I' + os.path.join(lib, 'include'), main,
                    os.path.join(lib, 'src', 'font', 'Pfr1Font.cpp'),
                    os.path.join(lib, 'src', 'font', 'PfrBitReader.cpp'), '-o', exe], check=True)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    decompile(sys.argv[1])
    build_pfr1json()
