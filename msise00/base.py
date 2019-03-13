"""
Call NRL MSISE-00 using f2py from Python
Michael Hirsch, Ph.D.

Original fortran code from
http://nssdcftp.gsfc.nasa.gov/models/atmospheric/msis/nrlmsise00/
"""
from datetime import datetime, date
import xarray
import numpy as np
import subprocess
from typing import Union, List
from pathlib import Path
from dateutil.parser import parse
import io

import geomagindices as gi

R = Path(__file__).resolve().parents[1] / 'build'
EXE = R / 'msise00_driver'
if not EXE.is_file():
    raise FileNotFoundError(f'Need to compile MSIS, missing {EXE}')

species = ['He', 'O', 'N2', 'O2', 'Ar', 'Total', 'H', 'N', 'AnomalousO']
ttypes = ['Texo', 'Tn']
first = True


def run(time: datetime, altkm: float,
        glat: Union[float, np.ndarray], glon: Union[float, np.ndarray]) -> xarray.Dataset:
    """
    loops the rungtd1d function below. Figure it's easier to troubleshoot in Python than Fortran.
    """
    glat = np.atleast_2d(glat)
    glon = np.atleast_2d(glon)  # has to be here
# %% altitude 1-D
    if glat.size == 1 and glon.size == 1 and isinstance(time, (str, date, datetime, np.datetime64)):
        atmos = rungtd1d(time, altkm, glat.squeeze()[()], glon.squeeze()[()])
# %% lat/lon grid at 1 altitude
    else:
        atmos = loopalt_gtd(time, glat, glon, altkm)

    return atmos


def loopalt_gtd(time: datetime,
                glat: Union[float, np.ndarray], glon: Union[float, np.ndarray],
                altkm: Union[float, List[float], np.ndarray]) -> xarray.Dataset:
    """
    loop over location and time

    time: datetime or numpy.datetime64 or list of datetime or np.ndarray of datetime
    glat: float or 2-D np.ndarray
    glon: float or 2-D np.ndarray
    altkm: float or list or 1-D np.ndarray
    """
    glat = np.atleast_2d(glat)
    glon = np.atleast_2d(glon)
    assert glat.ndim == glon.ndim == 2

    times = np.atleast_1d(time)
    assert times.ndim == 1

    atmos = xarray.Dataset()

    for k, t in enumerate(times):
        print('computing', t)
        for i in range(glat.shape[0]):
            for j in range(glat.shape[1]):
                # atmos = xarray.concat((atmos, rungtd1d(t, altkm, glat[i,j], glon[i,j])),
                #                      data_vars='minimal',coords='minimal',dim='lon')
                atm = rungtd1d(t, altkm, glat[i, j], glon[i, j])
                atmos = xarray.merge((atmos, atm))

    atmos.attrs = atm.attrs

    return atmos


def rungtd1d(time: datetime,
             altkm: np.ndarray,
             glat: float, glon: float) -> xarray.Dataset:
    """
    This is the "atomic" function looped by other functions
    """
    time = todatetime(time)
    # %% get solar parameters for date
    f107Ap = gi.getApF107(time, smoothdays=81)
    f107a = f107Ap['f107s'].item()
    f107 = f107Ap['f107'].item()
    Ap = f107Ap['Ap'].item()
# %% dimensions
    altkm = np.atleast_1d(altkm)
    assert altkm.ndim == 1
    assert isinstance(glon, (int, float))
    assert isinstance(glat, (int, float))

# %%
    doy = time.strftime('%j')
    altkm = np.atleast_1d(altkm)
# %%
    dens = np.empty((altkm.size, len(species)))
    temp = np.empty((altkm.size, len(ttypes)))
    for i, a in enumerate(altkm):
        ret = subprocess.check_output([EXE,
                                       doy, str(time.hour), str(time.minute), str(time.second),
                                       str(glat), str(glon),
                                       str(f107a), str(f107a), str(Ap), str(a)],
                                      universal_newlines=True,
                                      stderr=subprocess.DEVNULL)
        f = io.StringIO(ret)
        dens[i, :] = np.genfromtxt(f, max_rows=1)
        temp[i, :] = np.genfromtxt(f, max_rows=1)

    dsf = {k: (('time', 'alt_km', 'lat', 'lon'), v[None, :, None, None]) for (k, v) in zip(species, dens.T)}
    dsf.update({'Tn':  (('time', 'alt_km', 'lat', 'lon'), temp[:, 1][None, :, None, None]),
                'Texo': (('time', 'alt_km', 'lat', 'lon'), temp[:, 0][None, :, None, None])})

    atmos = xarray.Dataset(dsf,
                           coords={'time': [time], 'alt_km': altkm, 'lat': [glat], 'lon': [glon], },
                           attrs={'Ap': Ap, 'f107': f107, 'f107a': f107a,
                                  'species': species})

    return atmos


def todt64(time: Union[str, datetime, np.datetime64, list, np.ndarray]) -> np.ndarray:
    time = np.atleast_1d(time)

    if time.size == 1:
        time = np.atleast_1d(np.datetime64(time[0], dtype='datetime64[us]'))
    elif time.size == 2:
        time = np.arange(time[0], time[1], dtype='datetime64[h]')
    else:
        pass

    return time


def todatetime(time) -> datetime:

    if isinstance(time, str):
        dtime = parse(time)
    elif isinstance(time, datetime):
        dtime = time
    elif isinstance(time, np.datetime64):
        dtime = time.astype(datetime)
    elif isinstance(time, (tuple, list, np.ndarray)):
        if len(time) == 1:
            dtime = todatetime(time[0])
        else:
            dtime = [todatetime(t) for t in time]
    else:
        raise TypeError(f'{type(time)} not allowed')

    if not isinstance(dtime, datetime) and isinstance(dtime, date):
        dtime = datetime.combine(dtime, datetime.min.time())

    return dtime
