# NOTICE

This project is effectively now unmaintained due to a GameMaker change that broke WINE compatability combined with an official Linux build of GameMaker now being provided.

# ABOUT

GMBuild-CLI is a tool that allows compiling GameMaker projects targeted for Windows on Linux through WINE. It requires that you have GameMaker installed, set up, and logged in through WINE. Once this is accomplished GMBuild-CLI will automatically scan for runtimes and login data to allow compiling through the terminal without having the editor open. Paired with GMEdit this makes for a solid workflow.

This is a very niche application and one that I have designed solely for personal use but am distributing in case anyone else may find it useful. This repo is a Python re-design of a previously existing personal project that was initially written in bash script. It has not reached feature parity yet and as this is my first real Python project in about a decade it will be rough around the edges.

The system is currently only tested / working for GameMaker runtimes 2.3.x.x as the newer versions of GameMaker have issues running under WINE.
