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
import json
import logging
import re
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from wand import image  # Requires: apt-get install libmagickwand-dev
from wand.api import library

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@dataclass
class DLC:
    name: str
    gfx_folder: Path
    interface_folders: List[Path]

    def __str__(self) -> str:
        return self.name


@dataclass
class SpriteType:
    name: str
    texturefile: Path
    frames: int
    dlc: Optional[DLC]

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, texturefile={self.texturefile!r})"


@dataclass
class IconSearchConfig:
    title: str
    template_path: Path
    favicon: Optional[str]
    replace_date: bool
    sections: Dict[
        str, Dict[str, Any]
    ]  # Each section: {"paths": List[Path], "remove_str": Optional[str]}
    modified_images: List[Path] = field(default_factory=list)
    dlcs: List[DLC] = field(default_factory=list)


def load_config(config_path: Path) -> IconSearchConfig:
    """Load configuration from a JSON file."""
    try:
        with config_path.open("r", encoding="utf8") as f:
            data = json.load(f)
    except Exception as e:
        logging.exception(f"Failed to load config file")
        raise

    # Parse sections (convert paths to Path objects)
    sections = {}
    for section, cfg in data.get("sections", {}).items():
        paths = [Path(p) for p in cfg.get("paths", [])]
        remove_str = cfg.get("remove_str", None)
        sections[section] = {"paths": paths, "remove_str": remove_str}

    # Parse modified_images
    modified_images = [Path(p) for p in data.get("modified_images", [])]

    # Parse DLCs (expect each as a dict with keys: name, gfx_folder, interface_folders)
    dlcs = []
    for dlc_data in data.get("dlcs", []):
        try:
            name = dlc_data["name"]
            gfx_folder = Path(dlc_data["gfx_folder"])
            interface_folders = [Path(p) for p in dlc_data.get("interface_folders", [])]
            dlcs.append(DLC(name, gfx_folder, interface_folders))
        except KeyError as e:
            logging.warning(f"Missing key in DLC configuration: {e}")

    return IconSearchConfig(
        title=data["title"],
        template_path=Path(data["template_path"]),
        favicon=data.get("favicon"),
        replace_date=data.get("replace_date", False),
        sections=sections,
        modified_images=modified_images,
        dlcs=dlcs,
    )


def get_case_insensitive_glob(pattern: Path) -> str:
    """Return a case-insensitive glob pattern for the given path."""
    return "".join(
        f"[{c.lower()}{c.upper()}]" if c.isalpha() else c for c in str(pattern)
    )


def try_case_insensitive_file(
    texturefile: Path, bad_files: List[Tuple[Any, str]]
) -> Path:
    """
    Try to find a file matching the given texturefile using a case-insensitive glob.
    If found, log the case discrepancy and return the found path.
    """
    pattern = get_case_insensitive_glob(texturefile)
    found_file = next(Path(".").glob(pattern), None)
    if found_file:
        msg = f"WRONG CASE: {texturefile} doesn't exist, but {found_file} does!"
        bad_files.append((str(texturefile), msg))
        logging.info(msg)
        return found_file
    return texturefile


class IconSearchGenerator:
    """
    Main class that encapsulates the logic for reading gfx files,
    converting images, and generating the HTML output.
    """

    def __init__(self, config: IconSearchConfig) -> None:
        self.config = config
        self.bad_files: List[Tuple[Any, str]] = []
        self.duplicates: Dict[str, List[Tuple[Any, Any, Any]]] = defaultdict(list)
        self.thread_workers = 8

    def convert_image(self, image_path: Path, frames: int) -> Optional[Path]:
        """Convert an image to PNG (cropping if multi-frame) using Wand."""
        if image_path.exists():
            fname = image_path.stem
            try:
                with image.Image(filename=str(image_path)) as img:
                    if frames > 1:
                        logging.info(f"{image_path} has {frames} frames, cropping...")
                        img.crop(0, 0, width=img.width // frames, height=img.height)
                    library.MagickSetCompressionQuality(img.wand, 0)
                    new_fname = image_path.parent / f"{fname}.png"
                    logging.info(f"Saving {new_fname}...")
                    img.auto_orient()
                    img.save(filename=str(new_fname))
                    return new_fname
            except Exception:
                msg = traceback.format_exc()
                self.bad_files.append((image_path, msg))
                logging.exception(f"EXCEPTION with {image_path}")
                return None
        else:
            msg = f"{image_path} does not exist!"
            self.bad_files.append((image_path, msg))
            logging.error(msg)
            return None

    def convert_images(
        self,
        gfx_files_list: List[Dict[str, List[SpriteType]]],
        updated_images: Optional[List[Path]] = None,
    ) -> None:
        """Convert images for all sprite types concurrently."""
        updated_set = set(updated_images) if updated_images else None
        with ThreadPoolExecutor(max_workers=self.thread_workers) as executor:
            futures = []
            for gfx_files in gfx_files_list:
                for path_str, sprite_list in gfx_files.items():
                    file_path = Path(path_str)
                    for sprite in sprite_list:
                        if updated_set and file_path not in updated_set:
                            continue
                        futures.append(
                            executor.submit(
                                self.convert_image, file_path, sprite.frames
                            )
                        )
            for future in futures:
                try:
                    future.result()
                except Exception:
                    msg = traceback.format_exc()
                    self.bad_files.append((file_path, msg))
                    logging.exception(f"EXCEPTION during image conversion")

    def read_gfx_file(
        self, gfx_paths: List[Path]
    ) -> Tuple[Dict[str, List[SpriteType]], Dict[str, List[SpriteType]]]:
        """
        Reads .gfx files, extracts sprite definitions, and returns two dictionaries:
          - Mapping sprite names to lists of SpriteType objects.
          - Mapping texture file paths to lists of SpriteType objects.
        """
        gfx: Dict[str, List[SpriteType]] = defaultdict(list)
        gfx_files: Dict[str, List[SpriteType]] = defaultdict(list)
        for path in gfx_paths:
            try:
                # Identify associated DLC if the file is inside any DLC interface folder
                maybe_dlc = next(
                    (
                        dlc
                        for dlc in self.config.dlcs
                        if any(
                            path.is_relative_to(folder)
                            for folder in dlc.interface_folders
                        )
                    ),
                    None,
                )
                content = path.read_text(encoding="utf8")
                content = re.sub(r"#.*\n", " ", content, flags=re.IGNORECASE).replace(
                    "\n", " "
                )
                sprite_blocks = re.findall(
                    r"spriteType\s*=\s*\{[^\{\}]*?\}", content, flags=re.IGNORECASE
                )
                for block in sprite_blocks:
                    name = ""
                    texturefile: Optional[Path] = None
                    frames = 1
                    try:
                        name_match = re.search(
                            r'\s+name\s*=\s*"(.*?)"', block, flags=re.IGNORECASE
                        )
                        if not name_match:
                            name_match = re.search(
                                r"\s+name\s*=\s*([^\s]+)", block, flags=re.IGNORECASE
                            )
                        if name_match:
                            name = name_match.group(1)

                        tex_match = re.search(
                            r'\s+texturefile\s*=\s*"(.*?)"', block, flags=re.IGNORECASE
                        )
                        if not tex_match:
                            tex_match = re.search(
                                r"\s+texturefile\s*=\s*([^\s]+)",
                                block,
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
                                        dlc_texturefile, self.bad_files
                                    )
                                if dlc_texturefile.exists():
                                    texturefile = dlc_texturefile
                            if texturefile and not texturefile.exists():
                                texturefile = try_case_insensitive_file(
                                    texturefile, self.bad_files
                                )
                        frames_match = re.search(
                            r"\s+noOfFrames\s*=\s*([0-9]+)", block, flags=re.IGNORECASE
                        )
                        if frames_match:
                            frames = int(frames_match.group(1))
                        if name and texturefile:
                            sprite = SpriteType(name, texturefile, frames, maybe_dlc)
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
                        msg = traceback.format_exc()
                        logging.exception(
                            f"EXCEPTION with sprite '{name}' and texturefile '{texturefile}' in {path}:\n{msg}"
                        )
            except Exception:
                msg = traceback.format_exc()
                self.bad_files.append((str(path), msg))
                logging.exception(f"EXCEPTION with {path}:\n{msg}")
        return gfx, gfx_files

    def read_section_gfx(
        self, section_paths: List[Path]
    ) -> Tuple[Dict[str, List[SpriteType]], Dict[str, List[SpriteType]]]:
        """
        Expand directories and glob patterns to .gfx files and read sprite definitions for a section.
        """
        expanded: List[Path] = []
        for path in section_paths:
            path_str = str(path)
            if "*" in path_str or "?" in path_str:
                # Expand glob patterns relative to the current directory.
                globbed = list(Path().glob(path_str))
                logging.info(f"Expanded glob pattern '{path_str}' to: {globbed}")
                expanded.extend(globbed)
            elif path.is_dir():
                expanded.extend(list(path.rglob("*.gfx")))
            else:
                expanded.append(path)
        return self.read_gfx_file(expanded)

    def generate_icons_section(
        self, icons: Dict[str, List[SpriteType]], remove_str: Optional[str] = None
    ) -> Tuple[List[str], int]:
        """
        Generate HTML snippet entries for a group of icons and return the entries along with a count.
        """
        icon_entries: List[str] = []
        icons_count = 0
        for key, sprite_list in icons.items():
            added = False
            maybe_dlc = next((sprite.dlc for sprite in sprite_list if sprite.dlc), None)
            for sprite in sprite_list:
                name = sprite.name
                texturefile = sprite.texturefile
                self.duplicates[name].append((texturefile, key, sprite.dlc))
                maybe_dlc_str = (
                    f" dlc-{str(sprite.dlc).lower().replace(' ', '-')}"
                    if sprite.dlc
                    else (
                        ""
                        if len(sprite_list) == 1
                        else f" hidedlc-{str(maybe_dlc).lower().replace(' ', '-')}"
                    )
                )
                img_src = texturefile.parent / f"{texturefile.stem}.png"
                if not img_src.exists():
                    try:
                        self.convert_image(texturefile, sprite.frames)
                    except Exception:
                        msg = traceback.format_exc()
                        self.bad_files.append((texturefile, msg))
                        logging.exception(f"EXCEPTION with {texturefile}")
                if img_src.exists():
                    if remove_str:
                        name = name.replace(remove_str, "")
                    if not added:
                        icons_count += 1
                        added = True
                    entry = (
                        f'\n          <div data-clipboard-text="{name}" data-search-text="{name}" title="{name}" class="icon{maybe_dlc_str}">\n'
                        f'            <img src="{img_src}" alt="{name}">\n'
                        "          </div>\n        "
                    )
                    icon_entries.append(entry)
        icon_entries.sort()
        return icon_entries, icons_count

    def generate_dlc_checkboxes(self) -> List[str]:
        """Generate HTML checkboxes for each DLC."""
        entries = []
        for dlc in self.config.dlcs:
            normalized = str(dlc).lower().replace(" ", "-")
            entry = f'<label><input type="checkbox" class="dlc-checkbox" value="{normalized}" checked onchange="toggleDLC(\'{normalized}\')"> {dlc}</label>'
            entries.append(entry)
        return entries

    def load_template(self) -> str:
        """Load the HTML template from the configured path."""
        if not self.config.template_path.exists():
            msg = f"Template file {self.config.template_path} does not exist!"
            logging.error(msg)
            raise RuntimeError(msg)
        return self.config.template_path.read_text(encoding="utf8")

    def generate_html(
        self,
        sections_data: Dict[
            str, Tuple[Dict[str, List[SpriteType]], Dict[str, List[SpriteType]]]
        ],
    ) -> None:
        """
        Replace tokens in the template with generated HTML sections and write out index.html.
        Tokens are expected in the form: @SECTION_ICONS and @SECTION_NUM.
        """
        html = self.load_template()
        for section, (sprites, _) in sections_data.items():
            token_prefix = section.upper()
            remove_str = self.config.sections.get(section, {}).get("remove_str")
            entries, count = self.generate_icons_section(sprites, remove_str)
            html = html.replace(f"@{token_prefix}_ICONS", "".join(entries))
            html = html.replace(f"@{token_prefix}_NUM", str(count))
        html = html.replace("@TITLE", self.config.title)
        html = html.replace(
            "@FAVICON", self.config.favicon if self.config.favicon else ""
        )
        if self.config.replace_date:
            html = html.replace("@UPDATE_DATE", str(datetime.datetime.utcnow()))
        dlc_checkboxes = self.generate_dlc_checkboxes()
        html = html.replace("@DLC_CHECKBOXES", "\n".join(dlc_checkboxes))
        logging.info(f"Writing {len(html)} characters to index.html...")
        with open("index.html", "w", encoding="utf8") as f:
            f.write(html)
        duplicates_report = {}
        for key, items in self.duplicates.items():
            dedup = []
            for item in items:
                if not any(existing[-1] == item[-1] for existing in dedup):
                    dedup.append(item)
            if len(dedup) > 1:
                duplicates_report[key] = dedup
        logging.info(f"Duplicates: {duplicates_report}")

    def run(self) -> None:
        """Orchestrate the processing of gfx files, image conversion, and HTML generation."""
        logging.info("Starting IconSearchGenerator...")
        sections_data: Dict[
            str, Tuple[Dict[str, List[SpriteType]], Dict[str, List[SpriteType]]]
        ] = {}
        gfx_files_list = []
        for section, cfg in self.config.sections.items():
            logging.info(f"Processing section: {section}")
            sprites, sprite_files = self.read_section_gfx(cfg.get("paths", []))
            sections_data[section] = (sprites, sprite_files)
            gfx_files_list.append(sprite_files)
        self.convert_images(gfx_files_list, self.config.modified_images)
        self.generate_html(sections_data)
        if self.bad_files:
            logging.warning("The following files had exceptions or other issues:")
            for file_entry, error in self.bad_files:
                logging.warning(f"{file_entry}\n{error}\n")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a static GFX search website using a configuration file."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to the JSON configuration file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    config = load_config(args.config)
    generator = IconSearchGenerator(config)
    generator.run()


if __name__ == "__main__":
    main()
