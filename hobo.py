import csv
import re
from datetime import datetime, timedelta, tzinfo
from io import StringIO

__version__ = "0.1.0-hobo3"

TIME_FMTS = [
    "%m/%d/%y %I:%M:%S %p",  # Hoboware export
    "%m/%d/%Y %H:%M",  # Excel
]

TZ_REGEX = re.compile(r"GMT\s?[-+]\d\d:\d\d")
SN_REGEX = re.compile(r"(?:LGR S/N: |Serial Number:)(\d+)")
TITLE_REGEX = re.compile(r"Plot Title:\s")


class TZFixedOffset(tzinfo):
    """
    A fixed-offset timezone implementation for HOBO format `GMT-07:00`.
    """

    def __init__(self, offset):
        if type(offset) in (int, float):
            self.offset_hrs = offset
        elif type(offset) == str:
            if not TZ_REGEX.match(offset) or offset[-2:] != "00":
                raise ValueError(offset)
            self.offset_hrs = int(offset[-6:-3])  # extract whole hour and sign
        else:
            raise ValueError(offset)
        self.offset = timedelta(hours=self.offset_hrs)

    def utcoffset(self, dt):
        return self.offset

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return str(self)

    def __str__(self):
        return "GMT%+03d:00" % self.offset_hrs

    def __eq__(self, other):
        return other is not None and self.offset == other.offset

    def __repr__(self):
        return str(self)


def timestamp(s, tz=None):
    """Parse a HOBO timestamp value to Python DateTime"""
    for fmt in TIME_FMTS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=tz) if tz else dt
        except ValueError as e:
            pass
    raise ValueError(
        'time data "%s" does not match formats: %s' % (s, ", ".join(TIME_FMTS))
    )


class HoboCSVReader(object):
    """
    Iterator over a HOBO CSV file, produces (timestamp, temperature, RH,
    battery) rows.
    :param str fname: CSV filename
    :param tzinfo as_timezone: explicit timezone to cast timestamps to
    :param bool strict: whether we should be strict or lenient in parsing CSV
    :raises Exception: if this doesn't appear to be a HOBOware or BoxCar exported CSV
    :raises ValueError: if required columns representing timestamp or temperature can't be located
    :ivar str fname:
    :ivar str title:
    :ivar str sn:
    :ivar tzinfo tz:
    :ivar tzinfo as_timezone:
    """

    def __init__(self, fname, as_timezone=None, strict=True):
        self.fname = fname
        self._f = open(fname, "rt", encoding="utf-8-sig")

        self._itimestamp, self._itemp, self._irh, self._ibatt, self.title, self.sn = (
            None,
            None,
            None,
            None,
            None,
            None,
        )
        header = self._find_headers()
        if self._itimestamp is None:
            raise ValueError("Unable to find required timestamp column!")
        if self._itemp is None:
            raise ValueError("Unable to find required temperature column!")

        tz_match = TZ_REGEX.search(header)
        self.tz = TZFixedOffset(tz_match.group()) if tz_match else None
        self.as_timezone = (
            TZFixedOffset(as_timezone)
            if type(as_timezone) in (int, float, str)
            else as_timezone
        )

        self._reader = csv.reader(self._f, strict=strict)

    @staticmethod
    def _find_col_timestamp(headers):
        for i, header in enumerate(headers):
            if "Date Time" in header:
                return i

    @staticmethod
    def _find_col_temperature(headers):
        for i, header in enumerate(headers):
            if "High Res. Temp." in header or "High-Res Temp" in header:
                return i
        for i, header in enumerate(headers):
            for s in ("Temp,", "Temp.", "Temperature"):
                if s in header:
                    return i

    @staticmethod
    def _find_col_rh(headers):
        for i, header in enumerate(headers):
            if "RH," in header:
                return i

    @staticmethod
    def _find_col_battery(headers):
        for i, header in enumerate(headers):
            if "Batt, V" in header:
                return i

    def _find_columns(self, header):
        """Find and set integer index for (timestamp, temp, RH, battery) as private ivars"""
        headers = next(csv.reader(StringIO(header)))
        self._itimestamp = self._find_col_timestamp(headers)
        self._itemp = self._find_col_temperature(headers)
        self._irh = self._find_col_rh(headers)
        self._ibatt = self._find_col_battery(headers)

    def _find_headers(self):
        while self._itimestamp is None:
            header = next(self._f)
            if self.title is None:
                self.title = TITLE_REGEX.sub("", header.strip())
            if self.sn is None:
                sn_match = SN_REGEX.search(header)
                self.sn = sn_match.groups()[0] if sn_match else None
            self._find_columns(header)
        return header

    def __iter__(self):
        """
        Iterator for accessing the actual CSV rows.

        :return: yields (timestamp, temperature, RH, battery)
        :rtype: tuple(datetime, float, float, float)
        """
        for row in self._reader:
            if not row[self._itemp].strip():  # is this too lenient?
                continue  # skip event-only rows
            if not row[0].strip():
                continue  # skip blank rows
            ts = timestamp(row[self._itimestamp], self.tz)
            if self.as_timezone:
                ts = ts.astimezone(self.as_timezone)
            temp = float(row[self._itemp])
            rh = (
                float(row[self._irh])
                if self._irh is not None and row[self._irh]
                else None
            )
            batt = float(row[self._ibatt]) if self._ibatt is not None else str("-")
            yield ts, temp, rh, batt

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._f.close()
