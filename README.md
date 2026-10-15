
![Chiaki Logo](assets/chiaki_wide.png)

# chiaki-jv

**Disclaimer:** This project is not endorsed or certified by Sony Interactive Entertainment LLC.

chiaki-jv is a fork of [gameblabla/chiaki-up](https://github.com/gameblabla/chiaki-up), a free, open source PlayStation 4 and PlayStation 5 Remote Play client for Android.

## Changes from Chiaki-Up

- Fixes for HEVC stuttering and video corruption: submit complete frames to the decoder, reject damaged frames, and request a fresh keyframe for recovery. A smaller stream MTU also addresses fragmentation on the tested cellular VPN connection.
- Lower controller input latency through unbuffered joystick dispatch, so stick input does not wait for Android's usual UI batching.
- The controller SELECT button presses the PS5 touchpad instead of Share. Hold it to keep the touchpad button down; release it to let go.
- Codec lifecycle and error-handling fixes, Android build cleanup, and regression tests for the streaming and input changes.

The streaming fixes were tested with a PS5 on Wi-Fi and through a cellular WireGuard VPN. Results will vary with the phone, controller, and network. See [RELEASE-V1.md](RELEASE-V1.md) for measurements, build prerequisites, and the full change list.

## Build and release notes

The fork starts at upstream commit `86e38bf`. The release branch is `chiaki-jv`, tagged `v1.0.0` / `v1.0.1` / `v1.1.0` / `v1.1.1` / `v1.1.2` (current). The Oboe submodule is pinned to the companion fork github.com/0xjc22/oboe (branch `chiaki-jv`, tag `chiaki-jv-n1`).

## TODO

- Lacks Microphone support

- Lacks HDR

- Merge some newer improvements from chiaki-ng


## About

Originally Created by Florian Märkl, minor improvements by gameblabla

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License version 3
as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Additional permission under GNU AGPL version 3 section 7

If you modify this program, or any covered work, by linking or
combining it with the OpenSSL project's OpenSSL library (or a
modified version of that library), containing parts covered by the
terms of the OpenSSL or SSLeay licenses, the Free Software Foundation
grants you additional permission to convey the resulting work.
Corresponding Source for a non-source form of such a combination
shall include the source code for the parts of OpenSSL used as well
as that of the covered work.
