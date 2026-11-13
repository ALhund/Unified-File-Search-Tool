# third_party

配布物に同梱するライセンス全文のうち、各パッケージに含まれていないもの。

- `LGPL-3.0.txt` / `GPL-3.0.txt`: Qt for Python（PySide6 / shiboken6）用。
  PySide6 の配布パッケージにはライセンス全文が含まれないため、FSF の原文（Debian/Ubuntu の /usr/share/common-licenses と同一）を置いている。

`tools/collect_licenses.py` が `licenses/` に集めるときに使う。
