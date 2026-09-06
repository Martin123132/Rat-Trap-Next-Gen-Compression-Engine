# Rat-Trap-Next-Gen-Compression-Engine Notice

Rat-Trap-Next-Gen-Compression-Engine is source-available software, not open-source software.

Required Notice: Copyright (c) 2026 TWO HANDS NETWORK LTD.
Required Notice: Rat-Trap is a product owned and published by TWO HANDS NETWORK LTD under its written agreements with the project's contributors.

Rat-Trap-Next-Gen-Compression-Engine is licensed under the PolyForm Noncommercial License 1.0.0. Personal, hobby, research, educational, public-interest, and other non-commercial uses are permitted under that license.

Commercial use requires a separate written license from the licensor. Commercial use includes, without limitation:

- bundling Rat-Trap-Next-Gen-Compression-Engine or derived code into a paid product;
- offering Rat-Trap-Next-Gen-Compression-Engine functionality through a hosted, managed, SaaS, cloud, API, or agent service;
- using Rat-Trap-Next-Gen-Compression-Engine in an enterprise product or commercial developer tool;
- using Rat-Trap-Next-Gen-Compression-Engine or derived code as part of a commercial AI coding, agent, memory, context, retrieval, or repository-analysis product;
- training, fine-tuning, distilling, evaluating, or improving a commercial AI model or commercial AI system using Rat-Trap-Next-Gen-Compression-Engine source code, documentation, tests, data formats, or derived materials;
- removing or obscuring copyright, license, attribution, or required notices.

The Rat-Trap compressor implementation was designed and built by Glyn Evans,
drawing on Motion-TimeSpace work by Martin Ollett. Authorship and ownership of
underlying intellectual property remain governed by the applicable written
agreements; this notice does not vary those agreements.

This notice does not limit rights you may have under fair use, fair dealing, or other applicable law. It is intended to make the licensor's permission boundaries clear before the repository is made public.

## Frozen Windows runtime inventory

The Rat-Trap 5.7.0 Windows executable also contains separately licensed
components. Windows release packages include their complete upstream licence
files under `THIRD-PARTY-LICENSES` or
`Legal/THIRD-PARTY-LICENSES`:

- Python 3.13.13;
- Tcl/Tk 8.6;
- PyInstaller 6.21.0 bootloader and run-time hooks;
- PyInstaller Hooks Contrib 2026.6;
- PyFastCDC 0.2.1;
- typing_extensions 4.15.0;
- python-zstandard 0.25.0;
- cryptography 49.0.0;
- OpenSSL 4.0.1, statically linked by the cryptography Windows wheel;
- CFFI 2.1.0 and its pycparser 3.0 dependency.

Those upstream licences apply only to their respective components and do not
replace Rat-Trap's licence.

Cryptography is available under Apache-2.0 or BSD-3-Clause. OpenSSL 4.0.1 is
available under Apache-2.0. CFFI is MIT-0, pycparser is BSD-3-Clause, and
PyInstaller Hooks Contrib is Apache-2.0. The release ZIP contains their exact
licence texts plus the cryptography wheel and Rust component SBOMs.

## Bundled third-party component: PyFastCDC

Rat-Trap 5.7 bundles PyFastCDC 0.2.1 for FastCDC 2020 content-defined
chunking. PyFastCDC is licensed separately under the MIT License:

MIT License

Copyright (c) 2026 Fallen_Breath

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Bundled third-party component: python-zstandard

Rat-Trap 5.7 bundles python-zstandard 0.25.0 for Zstandard compression.
python-zstandard is licensed separately under the BSD 3-Clause License:

Copyright (c) 2016, Gregory Szorc
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
