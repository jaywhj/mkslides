import datetime
import time
import frontmatter
import jinja2
import logging
import shutil

from pathlib import Path
from urllib.parse import urlparse

from config import Config
from constants import HTML_BACKGROUND_IMAGE_REGEX, HTML_IMAGE_REGEX, MD_IMAGE_REGEX

logger = logging.getLogger(__name__)


class MarkupGenerator:
    def __init__(
        self,
        config: Config,
        md_root_path: Path,
        output_directory_path: Path,
    ):

        # Config

        self.config = config

        # Paths

        self.md_root_path = md_root_path.resolve(strict=True)
        logger.info(f'Markdown root directory: "{self.md_root_path.absolute()}"')

        self.output_directory_path = output_directory_path.resolve(strict=False)
        logger.info(
            f'Requested output directory: "{self.output_directory_path.absolute()}"'
        )

        self.assets_path = Path("assets").resolve(strict=True)
        self.revealjs_path = Path(self.assets_path / "reveal.js-master").resolve(
            strict=True
        )

        self.output_assets_path = self.output_directory_path / "assets"
        self.output_revealjs_path = self.output_assets_path / "reveal-js"

        # Templates

        self.jinja2_environment = jinja2.Environment()
        self.jinja2_environment.loader = jinja2.FileSystemLoader(".")

    def clear_output_directory(self) -> None:
        if self.output_directory_path.exists():
            shutil.rmtree(self.output_directory_path)
            logger.info("Output directory already exists: deleted")

    def create_output_directory(self) -> None:
        self.output_directory_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output directory created")

        self.__copy(self.revealjs_path, self.output_revealjs_path)

    def process_markdown(self, input_path: Path) -> None:
        logger.info(f"Processing markdown")
        start_time = time.perf_counter()

        if input_path.is_dir():
            self.__process_markdown_directory()
        else:
            self.__process_markdown_file(input_path)

        end_time = time.perf_counter()
        logger.info(f"Finished processing markdown in {end_time - start_time:.2f} seconds")

    ################################################################################

    def __process_markdown_file(
        self,
        md_file: Path,
    ) -> tuple[dict, Path]:
        logger.info(f'Processing markdown file: "{md_file}"')

        # Retrieve the frontmatter metadata and the markdown content

        content = md_file.read_text()
        metadata, markdown = frontmatter.parse(content)

        # Get the relative path of reveal.js

        output_markup_path = self.output_directory_path / md_file.relative_to(
            self.md_root_path
        )
        output_markup_path = output_markup_path.with_suffix(".html")
        relative_revealjs_path = self.output_revealjs_path.relative_to(
            output_markup_path.parent, walk_up=True
        )

        revealjs_config = self.config.get("reveal.js")

        # Copy the theme CSS

        relative_theme_path = None
        if theme := self.config.get("slides", "theme"):
            relative_theme_path = self.__copy_theme(output_markup_path, theme)

        # Generate the markup from markdown

        # Refresh the templates here, so they have effect when live reloading
        slideshow_template = self.jinja2_environment.get_template(
            self.config.get("slides", "template")
        )

        # https://revealjs.com/markdown/#external-markdown
        markdown_data_options = {}
        for option in [
            "separator",
            "separator-vertical",
            "separator-notes",
            "charset",
        ]:
            if value := self.config.get("slides", option):
                markdown_data_options[option] = value

        markup = slideshow_template.render(
            theme=relative_theme_path,
            revealjs_path=relative_revealjs_path,
            markdown_data_options=markdown_data_options,
            markdown=markdown,
            revealjs_config=revealjs_config,
        )
        self.__create_file(output_markup_path, markup)

        # Copy images

        self.__copy_images(md_file, markdown)

        return metadata, output_markup_path

    def __process_markdown_directory(self) -> None:
        slideshows = []
        for md_file in self.md_root_path.glob("**/*.md"):
            (metadata, output_markup_path) = self.__process_markdown_file(md_file)

            slideshows.append(
                {
                    "title": metadata.get("title", md_file.stem),
                    "location": output_markup_path.relative_to(
                        self.output_directory_path
                    ),
                }
            )

        logger.info(f"Generating index")

        index_path = self.output_directory_path / "index.html"

        relative_theme_path = None
        if theme := self.config.get("index", "theme"):
            relative_theme_path = self.__copy_theme(index_path, theme)

        # Refresh the templates here, so they have effect when live reloading
        index_template = self.jinja2_environment.get_template(
            self.config.get("index", "template")
        )

        content = index_template.render(
            title=self.config.get("index", "title"),
            theme=relative_theme_path,
            slideshows=slideshows,
            build_datetime=datetime.datetime.now(),
        )
        self.__create_file(index_path, content)

    def __copy_images(self, md_file: Path, markdown: str) -> None:
        for regex in [MD_IMAGE_REGEX, HTML_IMAGE_REGEX, HTML_BACKGROUND_IMAGE_REGEX]:
            for m in regex.finditer(markdown):
                image = Path(md_file.parent, m.group("location")).resolve(strict=True)
                self.__copy_to_output_relative_to_md_root(image)

    def __copy_theme(self, file_using_theme_path: Path, theme: str) -> Path | str:
        if self.__is_absolute_url(theme):
            logger.info(f'Using theme "{theme}" is an absolute URL, no copy necessary')
            return theme

        theme_path = Path(theme).resolve(strict=True)
        logger.info(f'Using theme "{theme_path}"')

        theme_output_path = self.output_assets_path / theme_path.name
        self.__copy_to_output(theme_path, theme_output_path)

        relative_theme_path = theme_output_path.relative_to(
            file_using_theme_path.parent, walk_up=True
        )

        return relative_theme_path

    ################################################################################

    def __create_file(self, destination_path: Path, content: any) -> None:
        if destination_path.exists():
            destination_path.write_text(content)
            logger.info(f'Overwritten: "{destination_path}"')
        else:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            destination_path.write_text(content)
            logger.info(f'Created: "{destination_path}"')

    def __copy_to_output(self, source_path: Path, destination_path: Path) -> Path:
        self.__copy(source_path, destination_path)
        relative_path = destination_path.relative_to(self.output_directory_path)
        return relative_path

    def __copy_to_output_relative_to_md_root(self, source_path: Path) -> Path:
        source_path = source_path.resolve(strict=True)
        if not source_path.is_relative_to(self.md_root_path):
            logger.warning(
                f'"{source_path.absolute()}" is outside the markdown root directory, skipped!"'
            )
            return

        relative_path = source_path.relative_to(self.md_root_path)
        destination_path = self.output_directory_path / relative_path

        self.__copy(source_path, destination_path)

        return relative_path

    def __copy(self, source_path, destination_path) -> None:
        if source_path.is_dir():
            self.__copy_tree(source_path, destination_path)
        else:
            self.__copy_file(source_path, destination_path)

    def __copy_tree(self, source_path, destination_path) -> None:
        overwrite = destination_path.exists()
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, destination_path, dirs_exist_ok=True)

        action = "Overwritten" if overwrite else "Copied"
        logger.info(
            f'{action} directory "{source_path.absolute()}" to "{destination_path.absolute()}"'
        )

    def __copy_file(self, source_path, destination_path) -> None:
        overwrite = destination_path.exists()
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source_path, destination_path)

        action = "Overwritten" if overwrite else "Copied"
        logger.info(
            f'{action} file "{source_path.absolute()}" to "{destination_path.absolute()}"'
        )

    def __is_absolute_url(self, url: str) -> bool:
        return bool(urlparse(url).scheme)