# hoi4_icon_search_gen.py by Yard1 (Antoni Baum)
#
#  MIT License
#
# Copyright (c) 2020 Antoni Baum
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import re
import sys
import argparse
import datetime
import traceback
from collections import defaultdict
from pathlib import Path
from wand import image  # also requires apt-get install libmagickwand-dev
from wand.api import library

BAD_FILES = []


def convert_images(paths, updated_images=None):
    global BAD_FILES
    for x in paths:
        for path, value in x.items():
            path = Path(path)
            frames = value[0].frames
            if updated_images and not path in updated_images:
                continue
            try:
                convert_image(path, frames)
            except:
                print("EXCEPTION with %s" % path)
                ex_message = traceback.format_exc()
                BAD_FILES.append((path, ex_message))
                print(ex_message)


def convert_image(path, frames):
    global BAD_FILES
    if path.exists():
        fname = path.stem
        with image.Image(filename=path) as img:
            if frames > 1:
                print("%s has %d frames, cropping..." % (path, frames))
                img.crop(0, 0, width=img.width //
                         frames, height=img.height)
            library.MagickSetCompressionQuality(img.wand, 00)
            new_fname = path.parent.joinpath(fname + '.png')
            print("Saving %s..." % (new_fname))
            img.auto_orient()
            img.save(filename=new_fname)
            return new_fname
    ex_message = "%s does not exist!" % path
    BAD_FILES.append((path, ex_message))
    print(ex_message)
    return None


class SpriteType:
    def __init__(self, name, texturefile, frames):
        self.name = name
        self.texturefile = texturefile
        self.frames = frames

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


def get_case_insensitive_glob(path):
    return ''.join(['[%s%s]' % (c.lower(), c.upper()) if c.isalpha() else c for c in str(path)])


def read_gfx(gfx_paths):
    gfx_paths_expanded = []
    for path in gfx_paths:
        if path.is_dir():
            gfx_paths_expanded.extend(path.rglob("*.gfx"))
        else:
            gfx_paths_expanded.append(path)

    return read_gfx_file(gfx_paths_expanded)


def read_gfx_file(gfx_paths):
    global BAD_FILES
    gfx = {}
    gfx_files = defaultdict(list)
    for path in gfx_paths:
        try:
            path = Path(path)
            with open(path, 'r') as f:
                file_contents = f.read()
            file_contents = re.sub(r'#.*\n', ' ', file_contents, re.IGNORECASE)
            file_contents = file_contents.replace('\n', ' ')
            spriteTypes = re.findall(
                r'spriteType\s*=\s*\{[^\{\}]*?\}', file_contents, re.IGNORECASE)
            for spriteType in spriteTypes:
                name = ''
                texturefile = ''
                try:
                    noOfFrames = 1
                    match = re.search(r'\s+name\s*=\s*\"(.+?)\"',
                                      spriteType, re.IGNORECASE)
                    if not match:
                        match = re.search(r'\s+name\s*=\s*([^\s]+)',
                                        spriteType, re.IGNORECASE)
                    if match:
                        name = match.group(1)
                    match = re.search(r'\s+texturefile\s*=\s*\"(.+?)\"',
                                      spriteType, re.IGNORECASE)
                    if not match:
                        match = re.search(r'\s+texturefile\s*=\s*([^\s]+)',
                                        spriteType, re.IGNORECASE)
                    if match:
                        texturefile = str(match.group(1))
                        if texturefile[0] == "\\" or texturefile[0] == "/":
                            texturefile = texturefile[1:]
                        texturefile = Path(texturefile)
                        if not texturefile.exists():
                            case_insensitive_glob = get_case_insensitive_glob(
                                texturefile)
                            texturefile_new = next(
                                Path(".").glob(case_insensitive_glob), None)
                            if texturefile_new:
                                ex_message = "WRONG CASE: %s doesn't exist, but %s does!" % (
                                    str(texturefile), str(texturefile_new))
                                BAD_FILES.append(
                                    (str(texturefile), ex_message))
                                print(ex_message)
                                texturefile = texturefile_new
                    match = re.search(
                        r'\s+noOfFrames\s*=\s*([0-9]+)', spriteType, re.IGNORECASE)
                    if match:
                        noOfFrames = int(match.group(1))
                    if name and texturefile:
                        st = SpriteType(name, texturefile, noOfFrames)
                        gfx[name] = st
                        gfx_files[texturefile].append(st)
                except:
                    print("EXCEPTION with %s %s in %s" %
                          (name, texturefile, path))
                    ex_message = traceback.format_exc()
                    print(ex_message)
        except:
            print("EXCEPTION with %s" % path)
            ex_message = traceback.format_exc()
            BAD_FILES.append((str(path), ex_message))
            print(ex_message)

    return (gfx, gfx_files)


def generate_icons_section(icons_dict, path_dicts, remove_str=None):
    global BAD_FILES
    icon_entries = []
    icons_num = 0

    for key, icon in icons_dict.items():
        name = icon.name
        path = icon.texturefile
        img_src = path.parent.joinpath(path.stem + '.png')
        if not img_src.exists():
            try:
                frames = icon.frames
                convert_image(path, frames)
            except:
                print("EXCEPTION with %s" % path)
                ex_message = traceback.format_exc()
                BAD_FILES.append((path, ex_message))
                print(ex_message)
        if img_src.exists():
            if remove_str:
                name = name.replace(remove_str, "")
            icons_num += 1
            icon_entries.append('''
          <div data-clipboard-text="%s" data-search-text="%s" title="%s" class="icon">
            <img src="%s" alt="%s">
          </div>
        ''' % (name, name, name, img_src, name))
    return (icon_entries, icons_num)


def generate_html(goals, ideas, character_ideas, texticons, events, news_events, agencies, decisions, decisions_cat, decisions_pics, path_dicts, title, favicon, replace_date, template_path):
    if not template_path.exists():
        print("%s doesn't exist!" % str(template_path))
        sys.exit(1)
    with open(template_path, 'r', encoding="utf8") as f:
        html = f.read()

    goal_entries, goals_num = generate_icons_section(goals, path_dicts)

    html = html.replace('@GOALS_ICONS', ''.join(goal_entries))
    html = html.replace('@GOALS_NUM', str(goals_num))

    idea_entries, ideas_num = generate_icons_section(
        ideas, path_dicts, "GFX_idea_")

    html = html.replace('@IDEAS_ICONS', ''.join(idea_entries))
    html = html.replace('@IDEAS_NUM', str(ideas_num))

    character_idea_entries, character_ideas_num = generate_icons_section(
        character_ideas, path_dicts, "GFX_idea_")

    html = html.replace('@CHARACTER_IDEAS_ICONS', ''.join(character_idea_entries))
    html = html.replace('@CHARACTER_IDEAS_NUM', str(character_ideas_num))

    texticons_entries, texticons_num = generate_icons_section(
        texticons, path_dicts)

    html = html.replace('@TEXTICONS_ICONS', ''.join(texticons_entries))
    html = html.replace('@TEXTICONS_NUM', str(texticons_num))

    events_entries, events_num = generate_icons_section(events, path_dicts)

    html = html.replace('@EVENTS_ICONS', ''.join(events_entries))
    html = html.replace('@EVENTS_NUM', str(events_num))

    news_events_entries, news_events_num = generate_icons_section(
        news_events, path_dicts)

    html = html.replace('@NEWSEVENTS_ICONS', ''.join(news_events_entries))
    html = html.replace('@NEWSEVENTS_NUM', str(news_events_num))

    agencies_entries, agencies_num = generate_icons_section(
        agencies, path_dicts)

    html = html.replace('@AGENCIES_ICONS', ''.join(agencies_entries))
    html = html.replace('@AGENCIES_NUM', str(agencies_num))

    decisions_entries, decisions_num = generate_icons_section(
        decisions, path_dicts)

    html = html.replace('@DECISIONS_ICONS', ''.join(decisions_entries))
    html = html.replace('@DECISIONS_NUM', str(decisions_num))

    decisions_cat_entries, decisions_cat_num = generate_icons_section(
        decisions_cat, path_dicts)

    html = html.replace('@DECISIONSCAT_ICONS', ''.join(decisions_cat_entries))
    html = html.replace('@DECISIONSCAT_NUM', str(decisions_cat_num))

    decisions_pics_entries, decisions_pics_num = generate_icons_section(
        decisions_pics, path_dicts)

    html = html.replace('@DECISIONSPICS_ICONS',
                        ''.join(decisions_pics_entries))
    html = html.replace('@DECISIONSPICS_NUM', str(decisions_pics_num))

    html = html.replace('@TITLE', title)
    favicon = favicon if favicon else ""
    html = html.replace('@FAVICON', favicon)
    if replace_date:
        html = html.replace('@UPDATE_DATE', str(datetime.datetime.utcnow()))

    print("Writing %d characters to index.html..." % len(html))
    with open('index.html', 'w', encoding="utf8") as f:
        f.write(html)


def main():
    global BAD_FILES
    print("Starting hoi4_icon_search_gen...")
    args = setup_cli_arguments()
    if args.modified_images:
        args.modified_images = set(args.modified_images)
        print(args.modified_images)
    goals, goals_files = read_gfx(args.goals)
    ideas, ideas_files = read_gfx(args.ideas)
    character_ideas, character_ideas_files = read_gfx(args.character_ideas)
    texticons, texticons_files = read_gfx(args.texticons)
    events, events_files = read_gfx(args.events)
    news_events, news_events_files = read_gfx(args.news_events)
    agencies, agencies_files = read_gfx(args.agencies)
    decisions, decisions_files = read_gfx(args.decisions)
    decisions_cat, decisions_cat_files = read_gfx(args.decisions_cat)
    decisions_pics, decisions_pics_files = read_gfx(args.decisions_pics)
    path_dicts = [goals_files, ideas_files, character_ideas_files, texticons_files, events_files, news_events_files,
                  agencies_files, decisions_files, decisions_cat_files, decisions_pics_files]
    convert_images(path_dicts,
                   args.modified_images)
    generate_html(goals, ideas, character_ideas, texticons, events, news_events, agencies, decisions,
                  decisions_cat, decisions_pics, path_dicts, args.title, args.favicon, args.replace_date, args.template_path)
    print("The following files had exceptions or other issues:")
    for f in BAD_FILES:
        print(f[0])
        print(f[1])
        print()


def setup_cli_arguments():
    parser = argparse.ArgumentParser(
        description='')
    parser.add_argument('--title',
                        help='Webpage title', required=True)
    parser.add_argument('--template-path', dest="template_path",
                        help='Path to template file', required=False, default="github-pages/index.template")
    parser.add_argument('--favicon',
                        help='Path to webpage favicon', required=False)
    parser.add_argument('--goals', nargs='*',
                        help='Paths to goals (national focus) interface gfx files', required=False)
    parser.add_argument('--ideas', nargs='*',
                        help='Paths to ideas interface gfx files', required=False)
    parser.add_argument('--character-ideas', nargs='*',
                        help='Paths to character ideas interface gfx files', required=False)
    parser.add_argument('--texticons', nargs='*',
                        help='Paths to texticons interface gfx files', required=False)
    parser.add_argument('--events', nargs='*',
                        help='Paths to events interface gfx files', required=False)
    parser.add_argument('--news-events', nargs='*', dest="news_events",
                        help='Paths to news events interface gfx files', required=False)
    parser.add_argument('--agencies', nargs='*',
                        help='Paths to agencies interface gfx files', required=False)
    parser.add_argument('--decisions', nargs='*',
                        help='Paths to decisions interface gfx files', required=False)
    parser.add_argument('--decisions-cat', nargs='*', dest="decisions_cat",
                        help='Paths to decisions category interface gfx files', required=False)
    parser.add_argument('--decisions-pics', nargs='*', dest="decisions_pics",
                        help='Paths to decision category picture interface gfx files', required=False)
    parser.add_argument('--modified-images', nargs='*',
                        help='Paths to modified image files (If not set, will convert all images)', dest="modified_images", required=False)
    parser.add_argument('--modified-images-str', nargs='?',
                        help='Paths to modified image files (If not set, will convert all images)', dest="modified_images_str", required=False)
    parser.add_argument('--replace-date', default=False, action='store_true',
                        help='If used, will replace UTC date with the current one', dest="replace_date", required=False)

    def _parse_paths(paths):
        parsed_paths = []
        if not paths:
            return parsed_paths
        for path in paths:
            if not path:
                continue
            if Path(path).exists() and Path(path).is_dir():
                new_paths = list(Path(path).glob("*.gfx"))
            else:
                new_paths = list(Path(".").glob(path))
            print(f"Resolving {path} into {new_paths}")
            parsed_paths.extend(new_paths)
        return parsed_paths

    args = parser.parse_args()
    args.template_path = Path(args.template_path)
    args.goals = _parse_paths(args.goals)
    args.ideas = _parse_paths(args.ideas)
    args.character_ideas = _parse_paths(args.character_ideas)
    args.texticons = _parse_paths(args.texticons)
    args.events = _parse_paths(args.events)
    args.news_events = _parse_paths(args.news_events)
    args.agencies = _parse_paths(args.agencies)
    args.decisions = _parse_paths(args.decisions)
    args.decisions_cat = _parse_paths(args.decisions_cat)
    args.decisions_pics = _parse_paths(args.decisions_pics)
    if args.modified_images_str:
        args.modified_images_str = [x.replace("'", "") for x in re.findall(
            r"'[^']+'", args.modified_images_str)]
        args.modified_images = args.modified_images_str
    if args.modified_images:
        args.modified_images = _parse_paths(args.modified_images)
    return args


if __name__ == "__main__":
    main()
