#    Copyright 2015-2017 ARM Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Process the output of the cpu_cooling devices in the current
directory's trace.dat"""

import pandas as pd

from trappy.base import Base
from trappy.dynamic import register_ftrace_parser

def pivot_with_labels(dfr, data_col_name, new_col_name, mapping_label):
    """Pivot a :mod:`pandas.DataFrame` row into columns

    :param dfr: The :mod:`pandas.DataFrame` to operate on.

    :param data_col_name: The name of the column in the :mod:`pandas.DataFrame`
        which contains the values.

    :param new_col_name: The name of the column in the :mod:`pandas.DataFrame` that will
        become the new columns.

    :param mapping_label: A dictionary whose keys are the values in
        new_col_name and whose values are their
        corresponding name in the :mod:`pandas.DataFrame` to be returned.

    :type dfr: :mod:`pandas.DataFrame`
    :type data_col_name: str
    :type new_col_name: str
    :type mapping_label: dict

    Example:

        >>> dfr_in = pd.DataFrame({'cpus': ["000000f0",
        >>>                                 "0000000f",
        >>>                                 "000000f0",
        >>>                                 "0000000f"
        >>>                                 ],
        >>>                        'freq': [1, 3, 2, 6]})
        >>> dfr_in
               cpus  freq
        0  000000f0     1
        1  0000000f     3
        2  000000f0     2
        3  0000000f     6

        >>> map_label = {"000000f0": "A15", "0000000f": "A7"}
        >>> power.pivot_with_labels(dfr_in, "freq", "cpus", map_label)
           A15  A7
        0    1 NaN
        1    1   3
        2    2   3
        3    2   6

    """

    # There has to be a more "pandas" way of doing this.

    col_set = set(dfr[new_col_name])

    ret_series = {}
    for col in col_set:
        try:
            label = mapping_label[col]
        except KeyError:
            available_keys = ", ".join(mapping_label.keys())
            error_str = '"{}" not found, available keys: {}'.format(col,
                                                                 available_keys)
            raise KeyError(error_str)
        data = dfr[dfr[new_col_name] == col][data_col_name]

        ret_series[label] = data

    return pd.DataFrame(ret_series).fillna(method="pad")

def num_cpus_in_mask(mask):
    """Return the number of cpus in a cpumask"""

    mask = mask.replace(",", "")
    value = int(mask, 16)

    return bin(value).count("1")

def sanitize_mask(mask):
    """Return mask string to usable int value """
    return int(mask.replace(",", ""), 16)

def cpus_to_mask(cpus):
    """Returns the integer value of the list -> mask translation"""
    res = 0
    for cpu in cpus:
        res |= (1 << cpu)
    return res

def mask_to_cpus(mask):
    """Returns the list of the cpus present in the mask"""
    res = []
    # Remove '0b' prefix
    bits = list(bin(mask))[2::]
    # Reverse to LSB first order
    bits.reverse()
    for idx, bit in enumerate(bits):
        if bit == '1':
            res.append(idx)
    return res

class CpuOutPower(Base):
    """Process the cpufreq cooling power actor data in a ftrace dump"""

    unique_word = "thermal_power_cpu_limit"
    """The unique word that will be matched in a trace line"""

    name = "cpu_out_power"
    """The name of the :mod:`pandas.DataFrame` member that will be created in a
    :mod:`trappy.ftrace.FTrace` object"""

    pivot = "cpus"
    """The Pivot along which the data is orthogonal"""

    def get_all_freqs(self, mapping_label):
        """Get a :mod:`pandas.DataFrame` with the maximum frequencies allowed by the governor

        :param mapping_label: A dictionary that maps cpumasks to name
            of the cpu.
        :type mapping_label: dict

        :return: freqs are in MHz
        """

        dfr = self.data_frame

        return pivot_with_labels(dfr, "freq", "cpus", mapping_label) / 1000

    def plot_cdev_states(self, width=None, height=None, xlim="default",
                         ylim="range", drawstyle="default", cpus=None):
        """Plot the cooling device state evolution

        :param width: The width of the plot
        :type width: int

        :param height: The height of the plot
        :type height: int

        :param xlim: The xlim setting of the plot.
            See :func:`~trappy.plot_utils.set_lim`
        :type xlim: str or tuple of int

        :param ylim: The ylim setting of the plot
            See :func:`~trappy.plot_utils.set_lim`
        :type ylim: str or tuple of int

        :param drawstyle: The drawstyle setting of the plot
        :type drawstyle: str

        :param cpus: List of cpus to plot
            All are plotted by default
        :type cpus: list of int
        """
        from matplotlib import pyplot as plt
        from trappy.plot_utils import normalize_title, pre_plot_setup, post_plot_setup

        if len(self.data_frame) == 0:
            raise ValueError("Empty DataFrame")

        thermal_dfr = self.data_frame.copy()

        # Sanitize cpumasks
        thermal_dfr["cpus"] = thermal_dfr["cpus"].apply(sanitize_mask)

        # Find available cpumasks
        available_masks = []
        for mask in thermal_dfr["cpus"].unique().tolist():
            available_masks.append(mask)

        # Sanitize cpus
        if cpus is not None:
            global_mask = cpus_to_mask(cpus)

            # Find masks that match the requested CPUs
            # This can include other CPUs
            selected_masks = [m for m in available_masks if m & global_mask]

            if len(selected_masks) == 0:
                raise ValueError("No {} trace for CPUs {}".format(self.unique_word, cpus))

            thermal_dfr = thermal_dfr[
                thermal_dfr["cpus"].isin(selected_masks)
            ]

        cdevs = {}
        # At this point we've removed the cpumasks we don't care about
        for mask in thermal_dfr["cpus"].unique().tolist():
            cdevs[mask] = thermal_dfr[thermal_dfr["cpus"] == mask]["cdev_state"]

        # Prepare one subplot per cdev
        ax = pre_plot_setup(width, height, nrows = len(cdevs))

        several_graphs = len(cdevs) > 1

        for idx, (mask, df) in enumerate(cdevs.iteritems()):
            _ax = ax[idx] if several_graphs else ax

            cdev_title = "Cooling state evolution of CPUS {}".format(mask_to_cpus(mask))
            df.plot(ax=_ax, title=cdev_title, drawstyle=drawstyle)

            _ax.set_ylabel('Cooling state')
            # Add vertical guidelines
            _ax.yaxis.grid(True)
            # Ensure tick interval is 1 and not something with weird decimals
            states = df.unique().tolist()
            _ax.set_yticks(range(min(states), max(states) + 1))

            post_plot_setup(_ax, xlim=xlim, ylim=ylim)

register_ftrace_parser(CpuOutPower, "thermal")

class CpuInPower(Base):
    """Process the cpufreq cooling power actor data in a ftrace dump
    """

    unique_word = "thermal_power_cpu_get"
    """The unique word that will be matched in a trace line"""

    name = "cpu_in_power"
    """The name of the :mod:`pandas.DataFrame` member that will be created in a
    :mod:`trappy.ftrace.FTrace` object"""

    pivot = "cpus"
    """The Pivot along which the data is orthogonal"""

    def _get_load_series(self):
        """get a :mod:`pandas.Series` with the aggregated load"""

        dfr = self.data_frame
        load_cols = [s for s in dfr.columns if s.startswith("load")]

        load_series = dfr[load_cols[0]].copy()
        for col in load_cols[1:]:
            load_series += dfr[col]

        return load_series

    def get_load_data(self, mapping_label):
        """Return :mod:`pandas.DataFrame` suitable for plot_load()

        :param mapping_label: A Dictionary mapping cluster cpumasks to labels
        :type mapping_label: dict
        """

        dfr = self.data_frame
        load_series = self._get_load_series()
        load_dfr = pd.DataFrame({"cpus": dfr["cpus"], "load": load_series})

        return pivot_with_labels(load_dfr, "load", "cpus", mapping_label)

    def get_normalized_load_data(self, mapping_label):
        """Return a :mod:`pandas.DataFrame` for plotting normalized load data

        :param mapping_label: should be a dictionary mapping cluster cpumasks
            to labels
        :type mapping_label: dict
        """

        dfr = self.data_frame
        load_series = self._get_load_series()

        load_series *= dfr['freq']
        for cpumask in mapping_label:
            num_cpus = num_cpus_in_mask(cpumask)
            idx = dfr["cpus"] == cpumask
            max_freq = max(dfr[idx]["freq"])
            load_series[idx] = load_series[idx] / (max_freq * num_cpus)

        load_dfr = pd.DataFrame({"cpus": dfr["cpus"], "load": load_series})

        return pivot_with_labels(load_dfr, "load", "cpus", mapping_label)

    def get_all_freqs(self, mapping_label):
        """get a :mod:`pandas.DataFrame` with the "in" frequencies as seen by the governor

        .. note::

            Frequencies are in MHz
        """

        dfr = self.data_frame

        return pivot_with_labels(dfr, "freq", "cpus", mapping_label) / 1000

register_ftrace_parser(CpuInPower, "thermal")
