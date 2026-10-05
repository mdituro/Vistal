# Vistal

Vistal runs early-2000s Windows PC games from their original discs on SteamOS.
It targets "Games for Windows"-era titles such as Freelancer, Rise of Nations:
Rise of Legends, and Midtown Madness.

You point it at a disc image. On first launch it runs the game's own installer
inside a dedicated Proton prefix. After that, every launch goes straight into
the game. It plugs into ES-DE, the EmulationStation frontend that EmuDeck
installs, as a "Games for Windows" system.

- **3D acceleration through Proton.** Direct3D 8 to 11 goes through DXVK and
  older DirectDraw/Direct3D through WineD3D. Both run on Vulkan or OpenGL on the GPU.
- **Install and run from disc images.** It reads `.iso`, `.cue/.bin`, `.mds/.mdf`,
  `.nrg`, `.ccd/.img` and `.chd`, plus `.m3u` playlists for multi-disc games. It
  needs no root access and no FUSE.
- **Disc checks keep working.** Each disc appears inside Wine as a real CD-ROM
  drive with the original volume label and serial number.
- **Controllers.** Games with joystick support get the pad directly. Mouse and
  keyboard games get a per-game gamepad-to-keyboard/mouse layout. Hold Back+Start
  to quit any game.
- **Keyboard and mouse** work as they do for any Proton game.
- **No dependencies beyond Python 3.11**, which SteamOS already ships.

> **Status.** The disc reader, installer flow, Proton launching, controller
> mapping and ES-DE integration are covered by an automated test suite. The suite
> uses real ISO tooling and a stand-in for Proton. Vistal has **not yet been run
> on a Steam Deck with the actual retail discs**, so expect per-game tuning.
> Please report what works.

## Install

On the Steam Deck, switch to Desktop Mode and open Konsole:

```sh
git clone https://github.com/mdituro/vistal.git ~/vistal
~/vistal/install.sh --esde
```

This installs `~/.local/bin/vistal` and registers the ES-DE system. It then
runs `vistal doctor`, which reports anything missing.

You need at least one Proton build. In Steam, install **Proton 9.0** or
**Proton - Experimental** from Library → Tools. GE-Proton in
`~/.steam/root/compatibilitytools.d/` also works. Optional extras are used when
present:

| Tool | Used for |
|------|----------|
| `umu-launcher` | Preferred way to run Proton outside Steam |
| `fuseiso` | Mount images instead of extracting them once |
| `7z` or `bsdtar` | Discs that only carry a UDF filesystem |
| `chdman` | `.chd` images |
| `zenity` | Dialogs when started from ES-DE; preinstalled on SteamOS |
| `winetricks` | `vistal tricks` |

## Using it with ES-DE / EmuDeck

1. Run `vistal frontend esde`, or pass `--esde` to the installer. This adds a
   **Games for Windows** system and creates `<ROMs>/gfw/`.
2. Put disc images in `<ROMs>/gfw/`, for example `Freelancer.iso`.
3. Launch the game from ES-DE. The first launch shows the game's installer.
   Install it as you would on Windows, and the game starts when setup finishes.
4. Later launches start the game directly.

ES-DE gets three launch options per game. "Vistal (Proton)" is the default.
"Reinstall from disc" reruns the installer. "Wine configuration" opens winecfg
for that game's prefix.

ES-DE runs as a non-Steam game in Game Mode, so games launched through it run
inside Game Mode's gamescope session. Vistal keeps Steam's game ID so the game
window gets focus.

**Multi-disc games.** Create `Game.m3u` with one disc file per line. Vistal
inserts every disc at once, in drives D:, E:, F: and so on. If an installer
insists on the same drive, hold **Back + D-pad right** to swap the disc in D:.
`vistal disc Game.m3u 2` does the same from a terminal.

**Games that are already installed.** Point a `.vistal` file at the folder or
executable, or put the installed folder itself in the ROM directory. See below.

Other frontends can call the same command:

```sh
vistal launch /path/to/Game.iso
vistal frontend emulationstation   # classic EmulationStation (es_systems.cfg)
vistal frontend desktop            # .desktop entries for Steam's "Add a Non-Steam Game"
```

## How a launch works

1. **Identify.** The ROM file name and the disc's volume label are matched
   against game profiles in `vistal/data/games/`.
2. **Prepare discs.** The image is read with the built-in ISO 9660/Joliet reader.
   Files are extracted once into `~/.cache/vistal/discs/`, or mounted with
   fuseiso when available. A drive root holds the files plus `.windows-label`
   and `.windows-serial`, which Wine reports as the CD's label and serial.
3. **Prefix.** Each game gets its own Proton prefix in
   `~/.local/share/vistal/games/<id>/compat/`. Drive letters from D: upward are
   registered as CD-ROM drives.
4. **Install.** `autorun.inf` or a setup program starts from `D:\`, so the
   installer records D: as its source the way it would on Windows. Vistal then
   reads the Start Menu shortcuts the installer created to find the game's
   executable. When that is ambiguous, it asks.
5. **Play.** Proton runs through `umu-run`, the Steam Linux Runtime, or
   directly, in that order of preference. Proton's output goes to
   `~/.local/share/vistal/logs/`.

## Controllers

| `controller.mode` | Behaviour |
|-------------------|-----------|
| `native` | The game reads the pad itself, through DirectInput/XInput in Proton. |
| `mapped` | Vistal turns the pad into keyboard and mouse with a layout, and hides the pad from the game. |
| `off` | Vistal leaves controllers alone, for example to use only Steam Input. |

Built-in layouts are `desktop`, `rts`, `freelancer`, `driving` and `fps`. List
them with `vistal controller layouts` and inspect one with
`vistal controller show rts`. To customise a layout, copy it to
`~/.config/vistal/controller/<name>.toml` and edit it. The format is documented
in `vistal/controller/layout.py`. It supports sticks as mouse, scroll or keys,
key combinations, a precision-aim button, and hold-to-activate layers.

Installers always use the `desktop` layout. The left stick moves the cursor and
A clicks.

Back is never bound in the built-in layouts because it is the hotkey modifier:

- **Back + Start**, held, quits the game.
- **Back + D-pad right / left** swaps discs in multi-disc games.

Mapping needs write access to `/dev/uinput`, which SteamOS grants through
Steam's udev rules. `vistal doctor` checks it. In Game Mode, Steam Input sits in
front of all of this. Leave ES-DE's controller configuration on a gamepad
template and let Vistal do the per-game mapping. Alternatively, set
`controller.mode = "off"` and configure Steam Input yourself.

## Configuration

Settings are layered from lowest to highest precedence:

1. `vistal/data/defaults.toml`, which documents every key
2. `~/.config/vistal/config.toml`, your global preferences
3. the game profile, from `vistal/data/games/*.toml` or `~/.config/vistal/profiles/*.toml`
4. `~/.config/vistal/games/<game-id>.toml`, overrides for one game

`vistal config <rom>` prints the merged result. Some examples:

```toml
# ~/.config/vistal/games/freelancer.toml
[proton]
version = "GE-Proton9-20"   # or "experimental", or a folder path
fps_limit = 0

[prefix]
winver = "winxp"
virtual_desktop = "1280x800"

[controller]
layout = "fps"
```

```toml
# ~/ROMs/gfw/Freelancer.vistal: an already-installed game, or a downloaded installer
title = "Freelancer"
profile = "freelancer"
exe = "C:/Program Files (x86)/Microsoft Games/Freelancer/EXE/Freelancer.exe"
# installer = "setup_freelancer.exe"   # run this instead of a disc installer
# discs = ["Freelancer.iso"]           # keep the disc available while playing
```

Set `VISTAL_HOME=/run/media/mmcblk0p1/vistal` to keep prefixes and caches on
the SD card.

## Command reference

```text
vistal launch <rom> [--reinstall]   install on first use, then play
vistal install <rom>                run the installer only
vistal run <rom> <program> [args]   run a patch or tool inside the game's prefix
vistal set-exe <rom> <path>         change which executable starts the game
vistal info <rom>                   label, serial, installer, profile, install state
vistal config <rom>                 effective settings
vistal disc <rom> <n>               put disc n into the first CD drive
vistal kill <rom>                   stop the game
vistal winecfg <rom> | tricks <rom> <verbs...>
vistal list | profiles | protons | doctor
vistal ls <image> | extract <image> <dir> | cache [show|clean]
vistal shortcut <game-id> <dir>     write a .vistal file for an installed game
vistal frontend esde|emulationstation|desktop
vistal controller list|test|layouts|show [layout]
```

`<rom>` can be an image, a playlist, a `.vistal` file, a folder, or the id of an
installed game.

Official patches install with `vistal run <rom> /path/to/patch.exe`. For
example, apply the Freelancer 1.1 patch this way after the first install.

## Known limitations

- **Copy-protection DRM.** SafeDisc and SecuROM disc DRM does not work under
  Wine or on Windows 10 and later. Games that use it need the publisher's
  official no-disc update or a DRM-free re-release. Plain disc checks work,
  including volume-label and file checks.
- **CD audio music.** Red Book audio tracks, such as Midtown Madness music, are
  not played from images.
- **Games for Windows - LIVE.** The GFWL service is gone. Games that require it
  need a compatible replacement DLL. Put it in `prefix.copy_to_game_dir`, with a
  native `dll_overrides` entry.
- **Multiplayer.** Online play over DirectPlay or GameSpy needs community
  servers.
- **Executable names in profiles.** Some names are best-effort,
  notably for Rise of Legends. If detection picks the wrong program, use
  `vistal set-exe`.

## Development

```sh
pytest                 # needs genisoimage (or mkisofs) for the disc tests
./install.sh --dev     # link ~/.local/bin/vistal to this checkout
```

The code is pure standard-library Python. The main modules are:

| Module | Role |
|--------|------|
| `discimage` | Image formats and ISO 9660 |
| `media` | ROM resolution and disc preparation |
| `proton` | Proton discovery and launching |
| `prefix` | Prefix setup and drive letters |
| `launcher` | Install and play flow |
| `detect` and `lnk` | Finding the game executable |
| `controller/` | evdev/uinput mapper |
| `frontends` | ES-DE and other frontends |
