# hoi4_icon_search_gen.py by Yard1 (Antoni Baum)
#
#  MIT License
#
# Copyright (c) 2020-2025 Antoni Baum
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

#!/usr/bin/env python3

import argparse
import datetime
import re
import sys
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from wand import image  # Requires apt-get install libmagickwand-dev
from wand.api import library

# Global state variables (used for error reporting and duplicate tracking)
BAD_FILES: List[Tuple[Any, str]] = []
DUPLICATES: Dict[str, List[Tuple[Any, Any, Any]]] = defaultdict(list)


def convert_image(image_path: Path, frames: int) -> Optional[Path]:
    """
    Converts an image file to PNG format. If the image contains multiple frames,
    it crops the image accordingly.
    """
    if image_path.exists():
        fname = image_path.stem
        return
        try:
            with image.Image(filename=str(image_path)) as img:
                if frames > 1:
                    print(f"{image_path} has {frames} frames, cropping...")
                    img.crop(0, 0, width=img.width // frames, height=img.height)
                # Set compression quality to 0 (as in original code)
                library.MagickSetCompressionQuality(img.wand, 0)
                new_fname = image_path.parent / f"{fname}.png"
                print(f"Saving {new_fname}...")
                img.auto_orient()
                img.save(filename=str(new_fname))
                return new_fname
        except Exception:
            ex_message = traceback.format_exc()
            BAD_FILES.append((image_path, ex_message))
            print(f"EXCEPTION with {image_path}")
            print(ex_message)
            return None
    else:
        ex_message = f"{image_path} does not exist!"
        BAD_FILES.append((image_path, ex_message))
        print(ex_message)
        return None


def convert_images(
    path_dicts: Iterable[Dict[str, List[Any]]],
    updated_images: Optional[Iterable[Path]] = None,
) -> None:
    """
    Converts images for all sprite types provided in a list of dictionaries.
    Each dictionary should have a file path as key and a list of sprite objects as value.
    If `updated_images` is provided, only convert images whose paths are in that set.
    """
    max_workers = 8
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for path_dict in path_dicts:
            for path_str, sprite_list in path_dict.items():
                file_path = Path(path_str)
                for sprite in sprite_list:
                    # Only process if file is updated (if filtering is enabled)
                    if updated_images and file_path not in updated_images:
                        continue
                    futures.append(
                        executor.submit(convert_image, file_path, sprite.frames)
                    )
        for future in futures:
            try:
                future.result()
            except Exception:
                # Note: The error is already captured in convert_image so this is just a fallback.
                print(f"EXCEPTION occurred during image conversion.")
                ex_message = traceback.format_exc()
                BAD_FILES.append((file_path, ex_message))
                print(ex_message)


class DLC:
    """
    Represents a DLC with a name, associated gfx folder, and interface folders.
    """

    def __init__(
        self, name: str, gfx_folder: Path, interface_folders: List[Path]
    ) -> None:
        self.name = name
        self.gfx_folder = gfx_folder
        self.interface_folders = interface_folders

    def __str__(self) -> str:
        return self.name

    def __bool__(self) -> bool:
        return bool(self.name)


class SpriteType:
    """
    Represents a sprite type defined in a gfx file.
    """

    def __init__(
        self, name: str, texturefile: Path, frames: int, dlc: Optional[DLC]
    ) -> None:
        self.name = name
        self.texturefile = texturefile
        self.frames = frames
        self.dlc = dlc

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, texturefile={self.texturefile!r})"


def get_case_insensitive_glob(pattern: Path) -> str:
    """
    Returns a case-insensitive glob pattern for the given path.
    """
    return "".join(
        f"[{c.lower()}{c.upper()}]" if c.isalpha() else c for c in str(pattern)
    )


def try_case_insensitive_file(texturefile: Path) -> Path:
    """
    Tries to find a file matching the texturefile path using a case-insensitive glob.
    If found, reports the mismatch in case and returns the found path.
    """
    case_insensitive_pattern = get_case_insensitive_glob(texturefile)
    found_file = next(Path(".").glob(case_insensitive_pattern), None)
    if found_file:
        ex_message = f"WRONG CASE: {texturefile} doesn't exist, but {found_file} does!"
        BAD_FILES.append((str(texturefile), ex_message))
        print(ex_message)
        return found_file
    return texturefile


def read_gfx(
    gfx_paths: List[Path], dlcs: List[DLC]
) -> Tuple[Dict[str, List[SpriteType]], Dict[str, List[SpriteType]]]:
    """
    Expands directories into individual .gfx file paths and reads them.
    Returns a tuple of two dictionaries:
      - The first maps sprite names to lists of SpriteType objects.
      - The second maps texture file paths to lists of SpriteType objects.
    """
    expanded_paths: List[Path] = []
    for path in gfx_paths:
        if path.is_dir():
            expanded_paths.extend(path.rglob("*.gfx"))
        else:
            expanded_paths.append(path)
    return read_gfx_file(expanded_paths, dlcs)


def read_gfx_file(
    gfx_paths: List[Path], dlcs: List[DLC]
) -> Tuple[Dict[str, List[SpriteType]], Dict[str, List[SpriteType]]]:
    """
    Reads the contents of gfx files, extracts sprite definitions, and returns two dictionaries.
    """
    gfx: Dict[str, List[SpriteType]] = defaultdict(list)
    gfx_files: Dict[str, List[SpriteType]] = defaultdict(list)

    for path in gfx_paths:
        try:
            path = Path(path)
            # Identify associated DLC by checking if the file is in one of the DLC interface folders
            maybe_dlc = next(
                (
                    dlc
                    for dlc in dlcs
                    if any(
                        path.is_relative_to(folder) for folder in dlc.interface_folders
                    )
                ),
                None,
            )
            with path.open("r", encoding="utf8") as f:
                file_contents = f.read()
            # Remove comments and newlines for easier regex processing
            file_contents = re.sub(r"#.*\n", " ", file_contents, flags=re.IGNORECASE)
            file_contents = file_contents.replace("\n", " ")

            sprite_blocks = re.findall(
                r"spriteType\s*=\s*\{[^\{\}]*?\}", file_contents, flags=re.IGNORECASE
            )
            for sprite_block in sprite_blocks:
                name = ""
                texturefile: Optional[Path] = None
                no_of_frames = 1
                try:
                    # Parse the name value
                    name_match = re.search(
                        r'\s+name\s*=\s*"(.*?)"', sprite_block, flags=re.IGNORECASE
                    )
                    if not name_match:
                        name_match = re.search(
                            r"\s+name\s*=\s*([^\s]+)", sprite_block, flags=re.IGNORECASE
                        )
                    if name_match:
                        name = name_match.group(1)

                    # Parse the texturefile value
                    tex_match = re.search(
                        r'\s+texturefile\s*=\s*"(.*?)"',
                        sprite_block,
                        flags=re.IGNORECASE,
                    )
                    if not tex_match:
                        tex_match = re.search(
                            r"\s+texturefile\s*=\s*([^\s]+)",
                            sprite_block,
                            flags=re.IGNORECASE,
                        )
                    if tex_match:
                        tex_str = tex_match.group(1)
                        if tex_str.startswith("\\") or tex_str.startswith("/"):
                            tex_str = tex_str[1:]
                        texturefile = Path(tex_str)
                        if maybe_dlc:
                            dlc_texturefile = maybe_dlc.gfx_folder / texturefile
                            if not dlc_texturefile.exists():
                                dlc_texturefile = try_case_insensitive_file(
                                    dlc_texturefile
                                )
                            if dlc_texturefile.exists():
                                texturefile = dlc_texturefile
                        if texturefile and not texturefile.exists():
                            texturefile = try_case_insensitive_file(texturefile)

                    # Parse the number of frames
                    frames_match = re.search(
                        r"\s+noOfFrames\s*=\s*([0-9]+)",
                        sprite_block,
                        flags=re.IGNORECASE,
                    )
                    if frames_match:
                        no_of_frames = int(frames_match.group(1))

                    if name and texturefile:
                        sprite = SpriteType(name, texturefile, no_of_frames, maybe_dlc)
                        # Replace duplicate sprite for same DLC if found
                        if not any(
                            existing.texturefile == sprite.texturefile
                            for existing in gfx[name]
                        ):
                            replaced = False
                            for i, existing in enumerate(gfx[name]):
                                if existing.dlc == sprite.dlc:
                                    gfx[name][i] = sprite
                                    replaced = True
                            if not replaced:
                                gfx[name].append(sprite)
                            gfx_files[str(texturefile)].append(sprite)
                except Exception:
                    print(
                        f"EXCEPTION with sprite '{name}' and texturefile '{texturefile}' in {path}"
                    )
                    ex_message = traceback.format_exc()
                    print(ex_message)
        except Exception:
            print(f"EXCEPTION with {path}")
            ex_message = traceback.format_exc()
            BAD_FILES.append((str(path), ex_message))
            print(ex_message)

    return gfx, gfx_files


def normalize_dlc_name(dlc: DLC) -> str:
    """
    Normalizes a DLC name for use in CSS classes.
    """
    return str(dlc).lower().replace(" ", "-")


def generate_icons_section(
    icons_dict: Dict[str, List[SpriteType]], remove_str: Optional[str] = None
) -> Tuple[List[str], int]:
    """
    Generates HTML snippets for a group of icons.
    Returns a tuple with the list of HTML entries and the number of icons added.
    """
    icon_entries: List[str] = []
    icons_num = 0

    for key, icons in icons_dict.items():
        added_num = False
        # Get the first DLC associated with the icons (if any)
        maybe_dlc = next((icon.dlc for icon in icons if icon.dlc), None)
        for icon in icons:
            name = icon.name
            texturefile = icon.texturefile
            DUPLICATES[name].append((texturefile, key, icon.dlc))
            if icon.dlc:
                maybe_dlc_str = f" dlc-{normalize_dlc_name(icon.dlc)}"
            else:
                maybe_dlc_str = (
                    ""
                    if len(icons) == 1
                    else f" hidedlc-{normalize_dlc_name(maybe_dlc)}"
                )

            # Build the expected PNG file path
            img_src = texturefile.parent / f"{texturefile.stem}.png"
            if not img_src.exists():
                try:
                    convert_image(texturefile, icon.frames)
                except Exception:
                    print(f"EXCEPTION with {texturefile}")
                    ex_message = traceback.format_exc()
                    BAD_FILES.append((texturefile, ex_message))
                    print(ex_message)
            if img_src.exists():
                if remove_str:
                    name = name.replace(remove_str, "")
                if not added_num:
                    icons_num += 1
                    added_num = True
                entry = (
                    f'\n          <div data-clipboard-text="{name}" data-search-text="{name}" title="{name}" class="icon{maybe_dlc_str}">\n'
                    f'            <img src="{img_src}" alt="{name}">\n'
                    "          </div>\n        "
                )
                icon_entries.append(entry)
    icon_entries.sort()
    return icon_entries, icons_num


def generate_dlc_checkboxes(dlcs: List[DLC]) -> List[str]:
    """
    Generates HTML checkbox entries for each DLC.
    """
    entries = []
    for dlc in dlcs:
        normalized = normalize_dlc_name(dlc)
        entry = (
            f'<label><input type="checkbox" class="dlc-checkbox" value="{normalized}" '
            f"checked onchange=\"toggleDLC('{normalized}')\"> {dlc}</label>"
        )
        entries.append(entry)
    return entries


def generate_html(
    goals: Dict[str, List[SpriteType]],
    ideas: Dict[str, List[SpriteType]],
    character_ideas: Dict[str, List[SpriteType]],
    texticons: Dict[str, List[SpriteType]],
    events: Dict[str, List[SpriteType]],
    news_events: Dict[str, List[SpriteType]],
    agencies: Dict[str, List[SpriteType]],
    decisions: Dict[str, List[SpriteType]],
    decisions_cat: Dict[str, List[SpriteType]],
    decisions_pics: Dict[str, List[SpriteType]],
    title: str,
    favicon: Optional[str],
    replace_date: bool,
    template_path: Path,
    dlcs: List[DLC],
) -> None:
    """
    Reads the HTML template, replaces tokens with generated icon sections,
    and writes the output to index.html.
    """
    if not template_path.exists():
        print(f"{template_path} doesn't exist!")
        sys.exit(1)

    with template_path.open("r", encoding="utf8") as f:
        html = f.read()

    # Replace icon sections and their counts
    sections = [
        ("@GOALS_ICONS", "@GOALS_NUM", goals, None),
        ("@IDEAS_ICONS", "@IDEAS_NUM", ideas, "GFX_idea_"),
        (
            "@CHARACTER_IDEAS_ICONS",
            "@CHARACTER_IDEAS_NUM",
            character_ideas,
            "GFX_idea_",
        ),
        ("@TEXTICONS_ICONS", "@TEXTICONS_NUM", texticons, None),
        ("@EVENTS_ICONS", "@EVENTS_NUM", events, None),
        ("@NEWSEVENTS_ICONS", "@NEWSEVENTS_NUM", news_events, None),
        ("@AGENCIES_ICONS", "@AGENCIES_NUM", agencies, None),
        ("@DECISIONS_ICONS", "@DECISIONS_NUM", decisions, None),
        ("@DECISIONSCAT_ICONS", "@DECISIONSCAT_NUM", decisions_cat, None),
        ("@DECISIONSPICS_ICONS", "@DECISIONSPICS_NUM", decisions_pics, None),
    ]

    for icons_token, count_token, icons_dict, remove_str in sections:
        entries, num = generate_icons_section(icons_dict, remove_str)
        html = html.replace(icons_token, "".join(entries))
        html = html.replace(count_token, str(num))

    html = html.replace("@TITLE", title)
    html = html.replace("@FAVICON", favicon if favicon else "")
    if replace_date:
        html = html.replace("@UPDATE_DATE", str(datetime.datetime.utcnow()))

    dlc_checkboxes = generate_dlc_checkboxes(dlcs)
    html = html.replace("@DLC_CHECKBOXES", "\n".join(dlc_checkboxes))

    print(f"Writing {len(html)} characters to index.html...")
    with open("index.html", "w", encoding="utf8") as f:
        f.write(html)

    # Report duplicate icons
    duplicates = {}
    for k, v in DUPLICATES.items():
        dedup = []
        for icon in v:
            if not any(existing[-1] == icon[-1] for existing in dedup):
                dedup.append(icon)
        if len(dedup) > 1:
            duplicates[k] = dedup
    print(f"Duplicates: {duplicates}")


def setup_cli_arguments() -> argparse.Namespace:
    """
    Sets up and parses the command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Generate a static GFX search website for a game."
    )
    parser.add_argument("--title", help="Webpage title", required=True)
    parser.add_argument(
        "--template-path",
        dest="template_path",
        help="Path to template file",
        default="github-pages/index.template",
    )
    parser.add_argument("--favicon", help="Path to webpage favicon", required=False)
    parser.add_argument(
        "--goals",
        nargs="*",
        help="Paths to goals (national focus) interface gfx files",
        required=False,
    )
    parser.add_argument(
        "--ideas", nargs="*", help="Paths to ideas interface gfx files", required=False
    )
    parser.add_argument(
        "--character-ideas",
        nargs="*",
        help="Paths to character ideas interface gfx files",
        required=False,
    )
    parser.add_argument(
        "--texticons",
        nargs="*",
        help="Paths to texticons interface gfx files",
        required=False,
    )
    parser.add_argument(
        "--events",
        nargs="*",
        help="Paths to events interface gfx files",
        required=False,
    )
    parser.add_argument(
        "--news-events",
        nargs="*",
        dest="news_events",
        help="Paths to news events interface gfx files",
        required=False,
    )
    parser.add_argument(
        "--agencies",
        nargs="*",
        help="Paths to agencies interface gfx files",
        required=False,
    )
    parser.add_argument(
        "--decisions",
        nargs="*",
        help="Paths to decisions interface gfx files",
        required=False,
    )
    parser.add_argument(
        "--decisions-cat",
        nargs="*",
        dest="decisions_cat",
        help="Paths to decisions category interface gfx files",
        required=False,
    )
    parser.add_argument(
        "--decisions-pics",
        nargs="*",
        dest="decisions_pics",
        help="Paths to decision category picture interface gfx files",
        required=False,
    )
    parser.add_argument(
        "--modified-images",
        nargs="*",
        help="Paths to modified image files (If not set, will convert all images)",
        dest="modified_images",
        required=False,
    )
    parser.add_argument(
        "--modified-images-str",
        nargs="?",
        help="Paths to modified image files (If not set, will convert all images)",
        dest="modified_images_str",
        required=False,
    )
    parser.add_argument(
        "--replace-date",
        default=False,
        action="store_true",
        help="If used, will replace UTC date with the current one",
        dest="replace_date",
        required=False,
    )
    parser.add_argument(
        "--dlc",
        nargs="*",
        help=(
            "DLC and folder paths (everything in the folder will be associated with the DLC) "
            "in the format of DLC name:dlc gfx prefix:interface folder"
        ),
        dest="dlc",
        required=False,
    )

    def parse_paths(paths: Optional[List[str]]) -> List[Path]:
        """
        Converts a list of strings to a list of Path objects by resolving directories and file globs.
        """
        parsed_paths: List[Path] = []
        if not paths:
            return parsed_paths
        for p in paths:
            if not p:
                continue
            path_obj = Path(p)
            if path_obj.exists() and path_obj.is_dir():
                new_paths = list(path_obj.glob("*.gfx"))
            else:
                new_paths = list(Path(".").glob(p))
            print(f"Resolving {p} into {new_paths}")
            parsed_paths.extend(new_paths)
        return parsed_paths

    def parse_dlc_paths(dlc_paths: Optional[List[str]]) -> List[DLC]:
        """
        Parses DLC arguments in the format:
          DLC name:dlc gfx prefix:interface folder
        and returns a list of DLC objects.
        """
        dlc_to_paths: Dict[Tuple[str, str], List[Path]] = defaultdict(list)
        if not dlc_paths:
            return []
        for dlc_entry in dlc_paths:
            print(f"Trying to parse {dlc_entry}")
            try:
                # Split into three parts from the right (DLC name, dlc gfx prefix, interface folder)
                dlc_name, dlc_gfx_prefix, folder = dlc_entry.rsplit(":", maxsplit=2)
                dlc_to_paths[(dlc_name, dlc_gfx_prefix)].append(Path(folder))
            except ValueError:
                print(f"Invalid DLC format: {dlc_entry}")
        return [
            DLC(name, Path(gfx_prefix), paths)
            for (name, gfx_prefix), paths in dlc_to_paths.items()
        ]

    args = parser.parse_args()
    args.template_path = Path(args.template_path)
    args.goals = parse_paths(args.goals)
    args.ideas = parse_paths(args.ideas)
    args.character_ideas = parse_paths(args.character_ideas)
    args.texticons = parse_paths(args.texticons)
    args.events = parse_paths(args.events)
    args.news_events = parse_paths(args.news_events)
    args.agencies = parse_paths(args.agencies)
    args.decisions = parse_paths(args.decisions)
    args.decisions_cat = parse_paths(args.decisions_cat)
    args.decisions_pics = parse_paths(args.decisions_pics)
    if args.modified_images_str:
        # Extract image paths from the string (removing extra quotes)
        args.modified_images_str = [
            x.replace("'", "") for x in re.findall(r"'[^']+'", args.modified_images_str)
        ]
        args.modified_images = args.modified_images_str
    if args.modified_images:
        args.modified_images = parse_paths(args.modified_images)
    args.dlc = parse_dlc_paths(args.dlc)
    return args


def main() -> None:
    print("Starting hoi4_icon_search_gen...")
    args = setup_cli_arguments()

    # Convert modified_images list to a set for faster membership checking, if provided.
    modified_images_set: Optional[set] = (
        set(args.modified_images) if args.modified_images else None
    )

    # Read gfx files for all sections
    goals, goals_files = read_gfx(args.goals, args.dlc)
    ideas, ideas_files = read_gfx(args.ideas, args.dlc)
    character_ideas, character_ideas_files = read_gfx(args.character_ideas, args.dlc)
    texticons, texticons_files = read_gfx(args.texticons, args.dlc)
    events, events_files = read_gfx(args.events, args.dlc)
    news_events, news_events_files = read_gfx(args.news_events, args.dlc)
    agencies, agencies_files = read_gfx(args.agencies, args.dlc)
    decisions, decisions_files = read_gfx(args.decisions, args.dlc)
    decisions_cat, decisions_cat_files = read_gfx(args.decisions_cat, args.dlc)
    decisions_pics, decisions_pics_files = read_gfx(args.decisions_pics, args.dlc)

    # Combine file dictionaries into a list for image conversion
    path_dicts = [
        goals_files,
        ideas_files,
        character_ideas_files,
        texticons_files,
        events_files,
        news_events_files,
        agencies_files,
        decisions_files,
        decisions_cat_files,
        decisions_pics_files,
    ]
    convert_images(path_dicts, modified_images_set)

    generate_html(
        goals,
        ideas,
        character_ideas,
        texticons,
        events,
        news_events,
        agencies,
        decisions,
        decisions_cat,
        decisions_pics,
        args.title,
        args.favicon,
        args.replace_date,
        args.template_path,
        args.dlc,
    )

    print("The following files had exceptions or other issues:")
    for file_entry, error in BAD_FILES:
        print(file_entry)
        print(error)
        print()


if __name__ == "__main__":
    main()
