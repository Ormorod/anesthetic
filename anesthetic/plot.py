"""Lower-level plotting tools.

Routines that may be of use to users wishing for more fine-grained control may
wish to use.

- ``make_1d_axes``
- ``make_2d_axes``

to create a set of axes and legend proxies.

"""
import numpy as np
from pandas import Series, DataFrame
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde
from scipy.special import erf
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
from matplotlib.axes import Axes
try:
    from astropy.visualization import hist
except ImportError:
    pass
try:
    from anesthetic.kde import fastkde_1d, fastkde_2d
except ImportError:
    pass
import matplotlib.cbook as cbook
import matplotlib.lines as mlines
from matplotlib.ticker import MaxNLocator, AutoMinorLocator
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.transforms import Affine2D
from anesthetic.utils import nest_level
from anesthetic.utils import (sample_compression_1d, quantile,
                              triangular_sample_compression_2d,
                              iso_probability_contours,
                              match_contour_to_contourf)
from anesthetic.boundary import cut_and_normalise_gaussian


class AxesSeries(Series):
    """Anesthetic's axes version of `~pandas.Series`."""

    def __init__(self, data=None, index=None, fig=None, ncol=None, labels=None,
                 gridspec_kw=None, subplot_spec=None, *args, **kwargs):
        if data is None and index is not None:
            data = self.axes_series(index=index, fig=fig, ncol=ncol,
                                    gridspec_kw=gridspec_kw,
                                    subplot_spec=subplot_spec)
            self._set_xlabels(axes=data, labels=labels)
        super().__init__(data=data, index=index, *args, **kwargs)

    @property
    def _constructor(self):
        return AxesSeries

    @property
    def _constructor_expanddim(self):
        return AxesDataFrame

    @staticmethod
    def axes_series(index, fig, ncol=None, gridspec_kw=None,
                    subplot_spec=None):
        """Set up subplots for `AxesSeries`."""
        axes = Series(np.full(np.shape(index), None), index=index)
        if fig is None:
            fig = plt.figure()
        if ncol is None:
            ncol = int(np.ceil(np.sqrt(axes.index.size)))
        ncol = ncol
        nrow = int(np.ceil(axes.index.size / ncol))
        if gridspec_kw is None:
            gridspec_kw = {}
        wspace = gridspec_kw.pop('wspace', 0)
        if subplot_spec is None:
            gs = GridSpec(nrow, ncol, wspace=wspace, **gridspec_kw)
        else:
            gs = GridSpecFromSubplotSpec(nrow, ncol, wspace=wspace,
                                         subplot_spec=subplot_spec,
                                         **gridspec_kw)
        for p, g in zip(axes.index, gs):
            axes[p] = ax = fig.add_subplot(g)
            ax.set_yticks([])
        return axes

    @staticmethod
    def _set_xlabels(axes, labels, **kwargs):
        if labels is None:
            labels = {}
        labels = {p: labels[p] if p in labels else p for p in axes.index}
        for p, ax in axes.items():
            ax.set_xlabel(labels[p], **kwargs)

    def set_xlabels(self, labels, **kwargs):
        """Set the labels for the x-axes.

        Parameters
        ----------
            labels : dict
                Dictionary of the axes labels.
            kwargs
                Any kwarg that can be passed to `plt.xlabel`.

        """
        self._set_xlabels(axes=self, labels=labels, **kwargs)

    def tick_params(self, *args, **kwargs):
        """Apply `matplotlib.axes.tick_params` to entire `AxesSeries`."""
        for p, ax in self.items():
            ax.tick_params(*args, **kwargs)


class AxesDataFrame(DataFrame):
    """Anesthetic's axes version of `~pandas.DataFrame`."""

    def __init__(self, data=None, index=None, columns=None, fig=None,
                 lower=True, diagonal=True, upper=True, labels=None,
                 ticks='inner', gridspec_kw=None, subplot_spec=None,
                 *args, **kwargs):
        if data is None and index is not None and columns is not None:
            position = self._position_frame(index=index,
                                            columns=columns,
                                            lower=lower,
                                            diagonal=diagonal,
                                            upper=upper)
            data = self._axes_frame(position=position,
                                    fig=fig,
                                    gridspec_kw=gridspec_kw,
                                    subplot_spec=subplot_spec)
            self._set_labels(axes=data, labels=labels)
            index = data.index
            columns = data.columns
            self._tick_params(axes=data, direction=ticks, which='both')
        super().__init__(data=data,
                         index=index,
                         columns=columns,
                         *args, **kwargs)
        self.tick_params(axis='both', which='both', labelrotation=45,
                         labelsize='small')

    @property
    def _constructor(self):
        return AxesDataFrame

    @property
    def _constructor_sliced(self):
        return AxesSeries

    @staticmethod
    def _position_frame(index, columns, lower, diagonal, upper):
        """Compute positions with lower=-1, diagonal=0, upper=+1."""
        data = np.full((np.size(index), np.size(columns)), None)
        position = DataFrame(data=data, index=index, columns=columns)
        all_params = list(columns) + list(index)
        for j, y in enumerate(index):
            for i, x in enumerate(columns):
                if all_params.index(x) < all_params.index(y):
                    if lower:
                        position[x][y] = -1
                elif all_params.index(x) > all_params.index(y):
                    if upper:
                        position[x][y] = +1
                elif diagonal:
                    position[x][y] = 0
        return position

    @classmethod
    def _axes_frame(cls, position, fig, gridspec_kw=None, subplot_spec=None):
        """Set up subplots for `AxesDataFrame`."""
        axes = position.copy()
        axes.dropna(axis=0, how='all', inplace=True)
        axes.dropna(axis=1, how='all', inplace=True)
        if axes.size == 0:
            return axes
        if fig is None:
            fig = plt.figure()
        if gridspec_kw is None:
            gridspec_kw = {}
        hspace = gridspec_kw.pop('hspace', 0)
        wspace = gridspec_kw.pop('wspace', 0)
        if subplot_spec is None:
            gs = GridSpec(*axes.shape, hspace=hspace, wspace=wspace,
                          **gridspec_kw)
        else:
            gs = GridSpecFromSubplotSpec(*axes.shape,
                                         hspace=hspace, wspace=wspace,
                                         subplot_spec=subplot_spec,
                                         **gridspec_kw)
        axes[:][:] = None
        for j, y in enumerate(axes.index[::-1]):
            for i, x in enumerate(axes.columns):
                if position[x][y] is not None:
                    sx = list(axes[x].dropna())
                    sx = sx[0] if sx else None
                    sy = list(axes.T[y].dropna())
                    sy = sy[0] if sy else None
                    axes[x][y] = fig.add_subplot(
                        gs[axes.index.size - 1 - j, i], sharex=sx, sharey=sy
                    )
                    if position[x][y] == 0:
                        axes[x][y].twin = axes[x][y].twinx()
                        axes[x][y].twin.set_yticks([])
                        cls.make_diagonal(axes[x][y])
                        axes[x][y].position = 'diagonal'
                        axes[x][y].twin.xaxis.set_major_locator(
                            MaxNLocator(3, prune='both'))
                        axes[x][y].twin.xaxis.set_minor_locator(
                            AutoMinorLocator(1))
                        axes[x][y].yaxis.set_major_locator(
                            MaxNLocator(3, prune='both'))
                        axes[x][y].yaxis.set_minor_locator(AutoMinorLocator(1))
                    else:
                        if position[x][y] == 1:
                            axes[x][y].position = 'upper'
                            cls.make_offdiagonal(axes[x][y])
                        elif position[x][y] == -1:
                            axes[x][y].position = 'lower'
                            cls.make_offdiagonal(axes[x][y])
                        axes[x][y].yaxis.set_major_locator(
                            MaxNLocator(3, prune='both'))
                        axes[x][y].yaxis.set_minor_locator(AutoMinorLocator(1))
                    axes[x][y].xaxis.set_major_locator(
                        MaxNLocator(3, prune='both'))
                    axes[x][y].xaxis.set_minor_locator(AutoMinorLocator(1))
        return axes

    @staticmethod
    def make_diagonal(ax):
        """Link x and y axes limits."""

        class DiagonalAxes(type(ax)):
            def set_xlim(self, left=None, right=None, emit=True, auto=False,
                         xmin=None, xmax=None):
                super().set_ylim(bottom=left, top=right, emit=True, auto=auto,
                                 ymin=xmin, ymax=xmax)
                return super().set_xlim(left=left, right=right, emit=emit,
                                        auto=auto, xmin=xmin, xmax=xmax)

            def set_ylim(self, bottom=None, top=None, emit=True, auto=False,
                         ymin=None, ymax=None):
                super().set_xlim(left=bottom, right=top, emit=True, auto=auto,
                                 xmin=ymin, xmax=ymax)
                return super().set_ylim(bottom=bottom, top=top, emit=emit,
                                        auto=auto, ymin=ymin, ymax=ymax)

            def get_legend_handles_labels(self, *args, **kwargs):
                return self.twin.get_legend_handles_labels(*args, **kwargs)

            def legend(self, *args, **kwargs):
                return self.twin.legend(*args, **kwargs)

        ax.__class__ = DiagonalAxes

    @staticmethod
    def make_offdiagonal(ax):
        """Linking x to y axes limits in triangle plots."""

        class OffDiagonalAxes(type(ax)):
            def set_xlim(self, left=None, right=None, emit=True, auto=False,
                         xmin=None, xmax=None):
                left, right = super().set_xlim(left=left, right=right,
                                               emit=emit,
                                               auto=auto, xmin=xmin, xmax=xmax)
                if emit:
                    self.callbacks.process('xlim_changed', self)
                    # Call all other x-axes that are shared with this one
                    for other in self._shared_axes['x'].get_siblings(self):
                        if other is not self:
                            other.set_xlim(left, right, emit=False, auto=auto)
                return left, right

            def set_ylim(self, bottom=None, top=None, emit=True, auto=False,
                         ymin=None, ymax=None):
                bottom, top = super().set_ylim(bottom=bottom, top=top,
                                               emit=emit,
                                               auto=auto, ymin=ymin, ymax=ymax)
                if emit:
                    self.callbacks.process('ylim_changed', self)
                    # Call all other y-axes that are shared with this one
                    for other in self._shared_axes['y'].get_siblings(self):
                        if other is not self:
                            other.set_ylim(bottom, top, emit=False, auto=auto)
                return bottom, top

        ax.__class__ = OffDiagonalAxes

    @staticmethod
    def _set_labels(axes, labels, **kwargs):
        all_params = list(axes.columns) + list(axes.index)
        if labels is None:
            labels = {}
        labels = {p: labels[p] if p in labels else p for p in all_params}

        for y, axes_row in axes.iterrows():
            if axes_row.size:
                axes_row.dropna(inplace=True)
                axes_row.iloc[0].set_ylabel(labels[y], **kwargs)

        for x, axes_col in axes.items():
            if axes_col.size:
                axes_col.dropna(inplace=True)
                axes_col.iloc[-1].set_xlabel(labels[x], **kwargs)

    def set_labels(self, labels, **kwargs):
        """Set the labels for the axes.

        Parameters
        ----------
            labels : dict
                Dictionary of the axes labels.
            kwargs
                Any kwarg that can be passed to `plt.xlabel` or `plt.ylabel`.

        """
        self._set_labels(axes=self, labels=labels, **kwargs)

    @staticmethod
    def _tick_params(axes, direction='inner', **kwargs):
        if direction not in ['inner', 'outer', None]:
            raise ValueError("tick direction=%s was requested, but tick "
                             "direction can only be one of "
                             "['outer', 'inner', None]." % direction)

        # left and right ticks and labels
        for y, ax in axes.iterrows():
            ax_ = ax.dropna()
            if len(ax_) and direction == 'inner':
                for i, a in enumerate(ax_):
                    if i == 0:  # first column
                        if a.position == 'diagonal' and len(ax_) == 1:
                            a.tick_params('y', left=False, labelleft=False,
                                          **kwargs)
                        else:
                            a.tick_params('y', left=True, labelleft=True,
                                          **kwargs)
                    elif a.position == 'diagonal':  # not first column
                        tl = a.yaxis.majorTicks[0].tick1line.get_markersize()
                        a.tick_params('y', direction='out', length=tl / 2,
                                      left=True, labelleft=False, **kwargs)
                    else:  # not diagonal and not first column
                        a.tick_params('y', direction='inout',
                                      left=True, labelleft=False, **kwargs)
            elif len(ax_) and direction == 'outer':  # no inner ticks
                for a in ax_[1:]:
                    a.tick_params('y', left=False, labelleft=False, **kwargs)
            elif len(ax_) and direction is None:  # no ticks at all
                for a in ax_:
                    a.tick_params('y', left=False, right=False,
                                  labelleft=False, labelright=False, **kwargs)

        # bottom and top ticks and labels
        for x, ax in axes.items():
            ax_ = ax.dropna()
            if len(ax_):
                if direction == 'inner':
                    for i, a in enumerate(ax_):
                        if i == len(ax_) - 1:  # bottom row
                            a.tick_params('x', bottom=True, labelbottom=True,
                                          **kwargs)
                        else:  # not bottom row
                            a.tick_params('x', direction='inout',
                                          bottom=True, labelbottom=False,
                                          **kwargs)
                            if a.position == 'diagonal':
                                a.twin.tick_params('x', direction='inout',
                                                   bottom=True,
                                                   labelbottom=False, **kwargs)
                elif direction == 'outer':  # no inner ticks
                    for a in ax_[:-1]:
                        a.tick_params('x', bottom=False, labelbottom=False,
                                      **kwargs)
                elif direction is None:  # no ticks at all
                    for a in ax_:
                        a.tick_params('x', bottom=False, top=False,
                                      labelbottom=False, labeltop=False,
                                      **kwargs)

    def tick_params(self, *args, **kwargs):
        """Apply `matplotlib.axes.tick_params` to entire `AxesDataFrame`."""
        for y, rows in self.iterrows():
            for x, ax in rows.items():
                if isinstance(ax, Axes):
                    ax.tick_params(*args, **kwargs)

    def set_margins(self, m):
        """Apply `matplotlib.axes.set_xmargin` to entire `AxesDataFrame`."""
        unique_params = list(np.unique(list(self.index) + list(self.columns)))
        for y, rows in self.iterrows():
            for x, ax in rows.items():
                if isinstance(ax, Axes):
                    if x in unique_params:
                        xmin, xmax = ax.get_xlim()
                        xdelta = xmax - xmin
                        ax.set_xlim(xmin - m * xdelta, xmax + m * xdelta)
                        unique_params.remove(x)
                    if y in unique_params:
                        ymin, ymax = ax.get_ylim()
                        ydelta = ymax - ymin
                        ax.set_ylim(ymin - m * ydelta, ymax + m * ydelta)
                        unique_params.remove(y)

    def axlines(self, params, lower=True, diagonal=True, upper=True, **kwargs):
        """Add vertical and horizontal lines across all axes.

        Parameters
        ----------
        params : dict(array_like)
            Dictionary of parameter labels and desired values.
            Can provide more than one value per label.
        lower, diagonal, upper : bool
            Whether to plot the lines on the lower, diagonal,
            and/or upper triangle plots.
            Default: True
        kwargs
            Any kwarg that can be passed to `plt.axvline` or `plt.axhline`.

        """
        positions = ['lower' if lower else None,
                     'diagonal' if diagonal else None,
                     'upper' if upper else None]
        for y, rows in self.iterrows():
            for x, ax in rows.items():
                if ax is not None and ax.position in positions:
                    if x in params:
                        for v in np.atleast_1d(params[x]):
                            ax.axvline(v, **kwargs)
                    if y in params and ax.position != 'diagonal':
                        for v in np.atleast_1d(params[y]):
                            ax.axhline(v, **kwargs)

    def axspans(self, params, lower=True, diagonal=True, upper=True, **kwargs):
        """Add vertical and horizontal spans across all axes.

        Parameters
        ----------
        params : dict(array_like(2-tuple))
            Dictionary of parameter labels and desired value tuples.
            Can provide more than one value tuple per label.
            Each value tuple provides the min and max value for an axis span.
        lower, diagonal, upper : bool
            Whether to plot the spans on the lower, diagonal,
            and/or upper triangle plots.
            Default: True
        kwargs
            Any kwarg that can be passed to `plt.axvspan` or `plt.axhspan`.

        """
        kwargs = normalize_kwargs(kwargs, dict(color=['c']))
        positions = ['lower' if lower else None,
                     'diagonal' if diagonal else None,
                     'upper' if upper else None]
        for y, rows in self.iterrows():
            for x, ax in rows.items():
                if ax is not None and ax.position in positions:
                    if x in params:
                        for vmin, vmax in np.atleast_2d(params[x]):
                            ax.axvspan(vmin, vmax, **kwargs)
                    if y in params and ax.position != 'diagonal':
                        for vmin, vmax in np.atleast_2d(params[y]):
                            ax.axhspan(vmin, vmax, **kwargs)

    def scatter(self, params, lower=True, upper=True, **kwargs):
        """Add scatter points across all axes.

        Parameters
        ----------
        params : dict(array_like)
            Dictionary of parameter labels and desired values.
            Can provide more than one value per label, but length has to
            match for all parameter labels.
        lower, upper : bool
            Whether to plot the spans on the lower and/or upper triangle plots.
            Default: True
        kwargs
            Any kwarg that can be passed to `plt.scatter`.

        """
        positions = ['lower' if lower else None,
                     'upper' if upper else None]
        zorder = kwargs.pop('zorder', None)
        for y, rows in self.iterrows():
            for x, ax in rows.items():
                if ax is not None and ax.position in positions:
                    if x in params and y in params:
                        z = max([z.get_zorder() for z in ax.artists +
                                 ax.collections + ax.lines + ax.patches] + [0])
                        z = z+1 if zorder is None else zorder
                        ax.scatter(params[x], params[y], zorder=z, **kwargs)


def make_1d_axes(params, ncol=None, labels=None,
                 gridspec_kw=None, subplot_spec=None, **fig_kw):
    """Create a set of axes for plotting 1D marginalised posteriors.

    Parameters
    ----------
    params : list(str)
        names of parameters.

    ncol : int
        Number of columns of the subplot grid.
        Default: ceil(sqrt(num_params))

    labels : dict(str:str), optional
        Dictionary mapping params to plot labels.
        Default: params

    gridspec_kw : dict, optional
        Dict with keywords passed to the `~matplotlib.gridspec.GridSpec`
        constructor used to create the grid the subplots are placed on.

    subplot_spec : matplotlib.gridspec.GridSpec, optional
        GridSpec instance to plot array as part of a subfigure.
        Default: None

    **fig_kw
        All additional keyword arguments are passed to the
        `.pyplot.figure` call.
        Or directly pass the figure to plot on via the keyword 'fig'.

    Returns
    -------
    fig : `~matplotlib.figure.Figure`
        New or original (if supplied) figure object.

    axes: `~pandas.Series(matplotlib.axes.Axes)`
        Pandas array of axes objects.

    """
    fig = fig_kw.pop('fig') if 'fig' in fig_kw else plt.figure(**fig_kw)
    axes = AxesSeries(index=np.atleast_1d(params),
                      fig=fig,
                      ncol=ncol,
                      labels=labels,
                      gridspec_kw=gridspec_kw,
                      subplot_spec=subplot_spec)
    if gridspec_kw is None:
        fig.tight_layout()
    return fig, axes


def make_2d_axes(params, labels=None, lower=True, diagonal=True, upper=True,
                 ticks='inner', gridspec_kw=None, subplot_spec=None, **fig_kw):
    """Create a set of axes for plotting 2D marginalised posteriors.

    Parameters
    ----------
    params : lists of parameters
        Can be either:
        * list(str) if the x and y axes are the same
        * [list(str),list(str)] if the x and y axes are different
        Strings indicate the names of the parameters

    labels : dict(str:str), optional
        Dictionary mapping params to plot labels.
        Default: params

    lower, diagonal, upper : logical, optional
        Whether to create 2D marginalised plots above or below the
        diagonal, or to create a 1D marginalised plot on the diagonal.
        Default: True

    ticks : str
        If 'outer', plot ticks only on the very left and very bottom.
        If 'inner', plot ticks also in inner subplots.
        If None, plot no ticks at all.
        Default: 'inner'

    gridspec_kw : dict, optional
        Dict with keywords passed to the `~matplotlib.gridspec.GridSpec`
        constructor used to create the grid the subplots are placed on.

    subplot_spec : matplotlib.gridspec.GridSpec, optional
        GridSpec instance to plot array as part of a subfigure.
        Default: None

    **fig_kw
        All additional keyword arguments are passed to the
        `.pyplot.figure` call.
        Or directly pass the figure to plot on via the keyword 'fig'.

    Returns
    -------
    fig : `~matplotlib.figure.Figure`
        New or original (if supplied) figure object.

    axes : `~pandas.DataFrame(matplotlib.axes.Axes)`
        Pandas array of axes objects.

    """
    fig = fig_kw.pop('fig') if 'fig' in fig_kw else plt.figure(**fig_kw)
    if nest_level(params) == 2:
        xparams, yparams = params
    else:
        xparams = yparams = params
    axes = AxesDataFrame(index=yparams,
                         columns=xparams,
                         fig=fig,
                         lower=lower,
                         diagonal=diagonal,
                         upper=upper,
                         labels=labels,
                         ticks=ticks,
                         gridspec_kw=gridspec_kw,
                         subplot_spec=subplot_spec)
    return fig, axes


def fastkde_plot_1d(ax, data, *args, **kwargs):
    """Plot a 1d marginalised distribution.

    This functions as a wrapper around matplotlib.axes.Axes.plot, with a kernel
    density estimation computation provided by the package fastkde in between.
    All remaining keyword arguments are passed onwards.

    Parameters
    ----------
    ax: matplotlib.axes.Axes
        Axis object to plot on.

    data: np.array
        Uniformly weighted samples to generate kernel density estimator.

    xmin, xmax: float
        lower/upper prior bound
        Optional, default None

    levels: list
        Values at which to draw iso-probability lines.
        Optional, default [0.95, 0.68]

    q: int or float or tuple
        Quantile to determine the data range to be plotted.
        - 0: full data range, i.e. q=0 --> quantile range (0, 1)
        - int: `q`-sigma data range, e.g. q=1 --> quantile range (0.16, 0.84)
        - float: percentile, e.g. q=0.68 --> quantile range  (0.16, 0.84)
        - tuple: quantile range, e.g. (0.16, 0.84)
        Default 5

    facecolor: bool or string
        If set to True then the 1d plot will be shaded with the value of the
        ``color`` kwarg. Set to a string such as 'blue', 'k', 'r', 'C1' ect.
        to define the color of the shading directly.
        Optional, default False

    Returns
    -------
    lines: matplotlib.lines.Line2D
        A list of line objects representing the plotted data (same as
        matplotlib matplotlib.axes.Axes.plot command).

    """
    kwargs = normalize_kwargs(
        kwargs,
        dict(linewidth=['lw'], linestyle=['ls'], color=['c'],
             facecolor=['fc'], edgecolor=['ec']))

    xmin = kwargs.pop('xmin', None)
    xmax = kwargs.pop('xmax', None)
    levels = kwargs.pop('levels', [0.95, 0.68])
    density = kwargs.pop('density', False)

    cmap = kwargs.pop('cmap', None)
    color = kwargs.pop('color', (next(ax._get_lines.prop_cycler)['color']
                                 if cmap is None else cmap(0.68)))
    facecolor = kwargs.pop('facecolor', False)
    if 'edgecolor' in kwargs:
        edgecolor = kwargs.pop('edgecolor')
        if edgecolor:
            color = edgecolor
    else:
        edgecolor = color

    q = kwargs.pop('q', 5)
    q = quantile_plot_interval(q=q)

    try:
        x, p, xmin, xmax = fastkde_1d(data, xmin, xmax)
    except NameError:
        raise ImportError("You need to install fastkde to use fastkde")
    p /= p.max()
    i = ((x > quantile(x, q[0], p)) & (x < quantile(x, q[-1], p)))

    area = np.trapz(x=x[i], y=p[i]) if density else 1
    ans = ax.plot(x[i], p[i]/area, color=color, *args, **kwargs)

    if facecolor and facecolor not in [None, 'None', 'none']:
        if facecolor is True:
            facecolor = color
        c = iso_probability_contours(p[i], contours=levels)
        cmap = basic_cmap(facecolor)
        fill = []
        for j in range(len(c)-1):
            fill.append(ax.fill_between(x[i], p[i], where=p[i] >= c[j],
                        color=cmap(c[j]), edgecolor=edgecolor))

        return ans, fill

    return ans


def kde_plot_1d(ax, data, *args, **kwargs):
    """Plot a 1d marginalised distribution.

    This functions as a wrapper around matplotlib.axes.Axes.plot, with a kernel
    density estimation computation provided by scipy.stats.gaussian_kde in
    between. All remaining keyword arguments are passed onwards.

    Parameters
    ----------
    ax: matplotlib.axes.Axes
        Axis object to plot on.

    data: np.array
        Samples to generate kernel density estimator.

    weights: np.array, optional
        Sample weights.

    ncompress: int, optional
        Degree of compression.
        If int: number of samples returned.
        If True: compresses to the channel capacity.
        If False: no compression.
        Default False

    nplot_1d: int, optional
        Number of plotting points to use.
        Default 100

    levels: list
        Values at which to draw iso-probability lines.
        Optional, default [0.95, 0.68]

    q: int or float or tuple
        Quantile to determine the data range to be plotted.
        - 0: full data range, i.e. q=0 --> quantile range (0, 1)
        - int: `q`-sigma data range, e.g. q=1 --> quantile range (0.16, 0.84)
        - float: percentile, e.g. q=0.68 --> quantile range  (0.16, 0.84)
        - tuple: quantile range, e.g. (0.16, 0.84)
        Default 5

    facecolor: bool or string
        If set to True then the 1d plot will be shaded with the value of the
        ``color`` kwarg. Set to a string such as 'blue', 'k', 'r', 'C1' ect.
        to define the color of the shading directly.
        Optional, default False

    Returns
    -------
    lines: matplotlib.lines.Line2D
        A list of line objects representing the plotted data (same as
        matplotlib matplotlib.axes.Axes.plot command).

    """
    kwargs = normalize_kwargs(
        kwargs,
        dict(linewidth=['lw'], linestyle=['ls'], color=['c'],
             facecolor=['fc'], edgecolor=['ec']))

    weights = kwargs.pop('weights', None)
    if weights is not None:
        data = data[weights != 0]
        weights = weights[weights != 0]

    ncompress = kwargs.pop('ncompress', False)
    nplot = kwargs.pop('nplot_1d', 100)
    bw_method = kwargs.pop('bw_method', None)
    levels = kwargs.pop('levels', [0.95, 0.68])
    density = kwargs.pop('density', False)

    cmap = kwargs.pop('cmap', None)
    color = kwargs.pop('color', (next(ax._get_lines.prop_cycler)['color']
                                 if cmap is None else cmap(0.68)))
    facecolor = kwargs.pop('facecolor', False)
    if 'edgecolor' in kwargs:
        edgecolor = kwargs.pop('edgecolor')
        if edgecolor:
            color = edgecolor
    else:
        edgecolor = color

    q = kwargs.pop('q', 5)
    q = quantile_plot_interval(q=q)
    xmin = quantile(data, q[0], weights)
    xmax = quantile(data, q[-1], weights)
    x = np.linspace(xmin, xmax, nplot)

    data_compressed, w = sample_compression_1d(data, weights, ncompress)
    kde = gaussian_kde(data_compressed, weights=w, bw_method=bw_method)

    p = kde(x)
    p /= p.max()
    bw = np.sqrt(kde.covariance[0, 0])
    pp = cut_and_normalise_gaussian(x, p, bw, xmin=data.min(), xmax=data.max())
    pp /= pp.max()
    area = np.trapz(x=x, y=pp) if density else 1
    ans = ax.plot(x, pp/area, color=color, *args, **kwargs)

    if facecolor and facecolor not in [None, 'None', 'none']:
        if facecolor is True:
            facecolor = color
        c = iso_probability_contours(pp, contours=levels)
        cmap = basic_cmap(facecolor)
        fill = []
        for j in range(len(c)-1):
            fill.append(ax.fill_between(x, pp, where=pp >= c[j],
                        color=cmap(c[j]), edgecolor=edgecolor))

        ans = ans, fill

    if density:
        ax.set_ylim(bottom=0)
    else:
        ax.set_ylim(0, 1.1)

    return ans


def hist_plot_1d(ax, data, *args, **kwargs):
    """Plot a 1d histogram.

    This functions is a wrapper around matplotlib.axes.Axes.hist. All remaining
    keyword arguments are passed onwards.

    Parameters
    ----------
    ax: matplotlib.axes.Axes
        Axis object to plot on.

    data: np.array
        Samples to generate histogram from

    weights: np.array, optional
        Sample weights.

    q: int or float or tuple
        Quantile to determine the data range to be plotted.
        - 0: full data range, i.e. q=0 --> quantile range (0, 1)
        - int: `q`-sigma data range, e.g. q=1 --> quantile range (0.16, 0.84)
        - float: percentile, e.g. q=0.68 --> quantile range  (0.16, 0.84)
        - tuple: quantile range, e.g. (0.16, 0.84)
        Default 5

    Returns
    -------
    patches : list or list of lists
        Silent list of individual patches used to create the histogram
        or list of such list if multiple input datasets.

    Other Parameters
    ----------------
    **kwargs : `~matplotlib.axes.Axes.hist` properties

    """
    weights = kwargs.pop('weights', None)
    bins = kwargs.pop('bins', 10)
    histtype = kwargs.pop('histtype', 'bar')
    density = kwargs.get('density', False)

    cmap = kwargs.pop('cmap', None)
    color = kwargs.pop('color', (next(ax._get_lines.prop_cycler)['color']
                                 if cmap is None else cmap(0.68)))

    q = kwargs.pop('q', 5)
    q = quantile_plot_interval(q=q)
    xmin = quantile(data, q[0], weights)
    xmax = quantile(data, q[-1], weights)

    if type(bins) == str and bins in ['knuth', 'freedman', 'blocks']:
        try:
            h, edges, bars = hist(data, ax=ax, bins=bins,
                                  range=(xmin, xmax), histtype=histtype,
                                  color=color, *args, **kwargs)
        except NameError:
            raise ImportError("You need to install astropy to use astropyhist")
    else:
        h, edges, bars = ax.hist(data, weights=weights, bins=bins,
                                 range=(xmin, xmax), histtype=histtype,
                                 color=color, *args, **kwargs)

    if histtype == 'bar' and not density:
        for b in bars:
            b.set_height(b.get_height() / h.max())
    elif (histtype == 'step' or histtype == 'stepfilled') and not density:
        trans = Affine2D().scale(sx=1, sy=1./h.max()) + ax.transData
        bars[0].set_transform(trans)

    if not density:
        ax.set_ylim(0, 1.1)
    return h, edges, bars


def fastkde_contour_plot_2d(ax, data_x, data_y, *args, **kwargs):
    """Plot a 2d marginalised distribution as contours.

    This functions as a wrapper around matplotlib.axes.Axes.contour, and
    matplotlib.axes.Axes.contourf with a kernel density estimation computation
    in between. All remaining keyword arguments are passed onwards to both
    functions.

    Parameters
    ----------
    ax: matplotlib.axes.Axes
        Axis object to plot on.

    data_x, data_y: np.array
        The x and y coordinates of uniformly weighted samples to generate
        kernel density estimator.

    levels: list
        Amount of mass within each iso-probability contour.
        Has to be ordered from outermost to innermost contour.
        Optional, default [0.95, 0.68]

    xmin, xmax, ymin, ymax: float
        The lower/upper prior bounds in x/y coordinates.
        Optional, default None

    Returns
    -------
    c: matplotlib.contour.QuadContourSet
        A set of contourlines or filled regions.

    """
    kwargs = normalize_kwargs(kwargs, dict(linewidths=['linewidth', 'lw'],
                                           linestyles=['linestyle', 'ls'],
                                           color=['c'],
                                           facecolor=['fc'],
                                           edgecolor=['ec']))

    xmin = kwargs.pop('xmin', None)
    xmax = kwargs.pop('xmax', None)
    ymin = kwargs.pop('ymin', None)
    ymax = kwargs.pop('ymax', None)
    label = kwargs.pop('label', None)
    zorder = kwargs.pop('zorder', 1)
    levels = kwargs.pop('levels', [0.95, 0.68])

    color = kwargs.pop('color', next(ax._get_lines.prop_cycler)['color'])
    facecolor = kwargs.pop('facecolor', True)
    edgecolor = kwargs.pop('edgecolor', None)
    cmap = kwargs.pop('cmap', None)
    facecolor, edgecolor, cmap = set_colors(c=color, fc=facecolor,
                                            ec=edgecolor, cmap=cmap)

    kwargs.pop('q', None)

    try:
        x, y, pdf, xmin, xmax, ymin, ymax = fastkde_2d(data_x, data_y,
                                                       xmin=xmin, xmax=xmax,
                                                       ymin=ymin, ymax=ymax)
    except NameError:
        raise ImportError("You need to install fastkde to use fastkde")

    levels = iso_probability_contours(pdf, contours=levels)

    i = (pdf >= levels[0]*0.5).any(axis=0)
    j = (pdf >= levels[0]*0.5).any(axis=1)

    if facecolor not in [None, 'None', 'none']:
        linewidths = kwargs.pop('linewidths', 0.5)
        contf = ax.contourf(x[i], y[j], pdf[np.ix_(j, i)], levels, cmap=cmap,
                            zorder=zorder, vmin=0, vmax=pdf.max(),
                            *args, **kwargs)
        for c in contf.collections:
            c.set_cmap(cmap)
        ax.add_patch(plt.Rectangle((0, 0), 0, 0, lw=2, label=label,
                                   fc=cmap(0.999), ec=cmap(0.32)))
        cmap = None
    else:
        linewidths = kwargs.pop('linewidths',
                                plt.rcParams.get('lines.linewidth'))
        contf = None
        ax.add_patch(
            plt.Rectangle((0, 0), 0, 0, lw=2, label=label,
                          fc='None' if cmap is None else cmap(0.999),
                          ec=edgecolor if cmap is None else cmap(0.32))
        )

    vmin, vmax = match_contour_to_contourf(levels, vmin=0, vmax=pdf.max())
    cont = ax.contour(x[i], y[j], pdf[np.ix_(j, i)], levels, zorder=zorder,
                      vmin=vmin, vmax=vmax, linewidths=linewidths,
                      colors=edgecolor, cmap=cmap, *args, **kwargs)

    ax.set_xlim(xmin, xmax, auto=True)
    ax.set_ylim(ymin, ymax, auto=True)
    return contf, cont


def kde_contour_plot_2d(ax, data_x, data_y, *args, **kwargs):
    """Plot a 2d marginalised distribution as contours.

    This functions as a wrapper around matplotlib.axes.Axes.tricontour, and
    matplotlib.axes.Axes.tricontourf with a kernel density estimation
    computation provided by scipy.stats.gaussian_kde in between. All remaining
    keyword arguments are passed onwards to both functions.

    Parameters
    ----------
    ax: matplotlib.axes.Axes
        Axis object to plot on.

    data_x, data_y: np.array
        The x and y coordinates of uniformly weighted samples to generate
        kernel density estimator.

    weights: np.array, optional
        Sample weights.

    levels: list, optional
        Amount of mass within each iso-probability contour.
        Has to be ordered from outermost to innermost contour.
        Optional, default [0.95, 0.68]

    ncompress: int, optional
        Degree of compression.
        If int: number of samples returned.
        If True: compresses to the channel capacity.
        If False: no compression.
        Default 1000

    nplot_2d: int, optional
        Number of plotting points to use.
        Default 1000

    Returns
    -------
    c: matplotlib.contour.QuadContourSet
        A set of contourlines or filled regions.

    """
    kwargs = normalize_kwargs(kwargs, dict(linewidths=['linewidth', 'lw'],
                                           linestyles=['linestyle', 'ls'],
                                           color=['c'],
                                           facecolor=['fc'],
                                           edgecolor=['ec']))

    weights = kwargs.pop('weights', None)
    if weights is not None:
        data_x = data_x[weights != 0]
        data_y = data_y[weights != 0]
        weights = weights[weights != 0]

    ncompress = kwargs.pop('ncompress', 1000)
    nplot = kwargs.pop('nplot_2d', 1000)
    bw_method = kwargs.pop('bw_method', None)
    label = kwargs.pop('label', None)
    zorder = kwargs.pop('zorder', 1)
    levels = kwargs.pop('levels', [0.95, 0.68])

    color = kwargs.pop('color', next(ax._get_lines.prop_cycler)['color'])
    facecolor = kwargs.pop('facecolor', True)
    edgecolor = kwargs.pop('edgecolor', None)
    cmap = kwargs.pop('cmap', None)
    facecolor, edgecolor, cmap = set_colors(c=color, fc=facecolor,
                                            ec=edgecolor, cmap=cmap)

    kwargs.pop('q', None)

    q = kwargs.pop('q', 5)
    q = quantile_plot_interval(q=q)
    xmin = quantile(data_x, q[0], weights)
    xmax = quantile(data_x, q[-1], weights)
    ymin = quantile(data_y, q[0], weights)
    ymax = quantile(data_y, q[-1], weights)
    X, Y = np.mgrid[xmin:xmax:1j*np.sqrt(nplot), ymin:ymax:1j*np.sqrt(nplot)]

    cov = np.cov(data_x, data_y, aweights=weights)
    tri, w = triangular_sample_compression_2d(data_x, data_y, cov,
                                              weights, ncompress)
    kde = gaussian_kde([tri.x, tri.y], weights=w, bw_method=bw_method)

    P = kde([X.ravel(), Y.ravel()]).reshape(X.shape)

    bw_x = np.sqrt(kde.covariance[0, 0])
    P = cut_and_normalise_gaussian(X, P, bw=bw_x,
                                   xmin=data_x.min(), xmax=data_x.max())
    bw_y = np.sqrt(kde.covariance[1, 1])
    P = cut_and_normalise_gaussian(Y, P, bw=bw_y,
                                   xmin=data_y.min(), xmax=data_y.max())

    levels = iso_probability_contours(P, contours=levels)

    if facecolor not in [None, 'None', 'none']:
        linewidths = kwargs.pop('linewidths', 0.5)
        contf = ax.contourf(X, Y, P, levels=levels, cmap=cmap, zorder=zorder,
                            vmin=0, vmax=P.max(), *args, **kwargs)
        for c in contf.collections:
            c.set_cmap(cmap)
        ax.add_patch(plt.Rectangle((0, 0), 0, 0, lw=2, label=label,
                                   fc=cmap(0.999), ec=cmap(0.32)))
        cmap = None
    else:
        linewidths = kwargs.pop('linewidths',
                                plt.rcParams.get('lines.linewidth'))
        contf = None
        ax.add_patch(
            plt.Rectangle((0, 0), 0, 0, lw=2, label=label,
                          fc='None' if cmap is None else cmap(0.999),
                          ec=edgecolor if cmap is None else cmap(0.32))
        )

    vmin, vmax = match_contour_to_contourf(levels, vmin=0, vmax=P.max())
    cont = ax.contour(X, Y, P, levels=levels, zorder=zorder,
                      vmin=vmin, vmax=vmax, linewidths=linewidths,
                      colors=edgecolor, cmap=cmap, *args, **kwargs)

    return contf, cont


def hist_plot_2d(ax, data_x, data_y, *args, **kwargs):
    """Plot a 2d marginalised distribution as a histogram.

    This functions as a wrapper around matplotlib.axes.Axes.hist2d

    Parameters
    ----------
    ax: matplotlib.axes.Axes
        Axis object to plot on.

    data_x, data_y: np.array
        The x and y coordinates of uniformly weighted samples to generate a
        two dimensional histogram.

    levels: list
        Shade iso-probability contours containing these levels of probability
        mass. If None defaults to usual matplotlib.axes.Axes.hist2d colouring.
        Optional, default None

    q: int or float or tuple
        Quantile to determine the data range to be plotted.
        - 0: full data range, i.e. q=0 --> quantile range (0, 1)
        - int: `q`-sigma data range, e.g. q=1 --> quantile range (0.16, 0.84)
        - float: percentile, e.g. q=0.68 --> quantile range  (0.16, 0.84)
        - tuple: quantile range, e.g. (0.16, 0.84)
        Default 5

    Returns
    -------
    c: matplotlib.collections.QuadMesh
        A set of colors.

    """
    weights = kwargs.pop('weights', None)

    vmin = kwargs.pop('vmin', 0)
    label = kwargs.pop('label', None)
    levels = kwargs.pop('levels', None)

    color = kwargs.pop('color', next(ax._get_lines.prop_cycler)['color'])
    cmap = kwargs.pop('cmap', basic_cmap(color))

    q = kwargs.pop('q', 5)
    q = quantile_plot_interval(q=q)
    xmin = quantile(data_x, q[0], weights)
    xmax = quantile(data_x, q[-1], weights)
    ymin = quantile(data_y, q[0], weights)
    ymax = quantile(data_y, q[-1], weights)
    rge = kwargs.pop('range', ((xmin, xmax), (ymin, ymax)))

    if levels is None:
        pdf, x, y, image = ax.hist2d(data_x, data_y, weights=weights,
                                     cmap=cmap, range=rge, vmin=vmin,
                                     *args, **kwargs)
    else:
        bins = kwargs.pop('bins', 10)
        density = kwargs.pop('density', False)
        cmin = kwargs.pop('cmin', None)
        cmax = kwargs.pop('cmax', None)
        pdf, x, y = np.histogram2d(data_x, data_y, bins, rge,
                                   density, weights)
        levels = iso_probability_contours(pdf, levels)
        pdf = np.digitize(pdf, levels, right=True)
        pdf = np.array(levels)[pdf]
        pdf = np.ma.masked_array(pdf, pdf < levels[1])
        if cmin is not None:
            pdf[pdf < cmin] = np.ma.masked
        if cmax is not None:
            pdf[pdf > cmax] = np.ma.masked
        image = ax.pcolormesh(x, y, pdf.T, cmap=cmap, vmin=vmin,
                              *args, **kwargs)

    ax.add_patch(plt.Rectangle((0, 0), 0, 0, fc=cmap(0.999), ec=cmap(0.32),
                               lw=2, label=label))

    return image


def scatter_plot_2d(ax, data_x, data_y, *args, **kwargs):
    """Plot samples from a 2d marginalised distribution.

    This functions as a wrapper around matplotlib.axes.Axes.plot, enforcing any
    prior bounds. All remaining keyword arguments are passed onwards.

    Parameters
    ----------
    ax: matplotlib.axes.Axes
        axis object to plot on

    data_x, data_y: np.array
        x and y coordinates of uniformly weighted samples to plot.

    Returns
    -------
    lines: matplotlib.lines.Line2D
        A list of line objects representing the plotted data (same as
        matplotlib.axes.Axes.plot command)

    """
    kwargs = normalize_kwargs(
        kwargs,
        dict(color=['c'], mfc=['facecolor', 'fc'], mec=['edgecolor', 'ec']),
        drop=['ls', 'lw'])
    kwargs = cbook.normalize_kwargs(kwargs, mlines.Line2D)

    markersize = kwargs.pop('markersize', 1)
    cmap = kwargs.pop('cmap', None)
    color = kwargs.pop('color', (next(ax._get_lines.prop_cycler)['color']
                                 if cmap is None else cmap(0.68)))

    kwargs.pop('q', None)

    points = ax.plot(data_x, data_y, 'o', color=color, markersize=markersize,
                     *args, **kwargs)
    return points


def basic_cmap(color):
    """Construct basic colormap a single color."""
    return LinearSegmentedColormap.from_list(color, ['#ffffff', color])


def quantile_plot_interval(q):
    """Interpret quantile q input to quantile plot range tuple."""
    if isinstance(q, str):
        sigmas = {'1sigma': 0.682689492137086,
                  '2sigma': 0.954499736103642,
                  '3sigma': 0.997300203936740,
                  '4sigma': 0.999936657516334,
                  '5sigma': 0.999999426696856}
        q = (1 - sigmas[q]) / 2
    elif isinstance(q, int) and q >= 1:
        q = (1 - erf(q / np.sqrt(2))) / 2
    if isinstance(q, float) or isinstance(q, int):
        if q > 0.5:
            q = 1 - q
        q = (q, 1-q)
    return tuple(np.sort(q))


def normalize_kwargs(kwargs, alias_mapping=None, drop=None):
    """Normalize kwarg inputs.

    Works the same way as cbook.normalize_kwargs, but additionally allows to
    drop kwargs.
    """
    drop = [] if drop is None else drop
    alias_mapping = {} if alias_mapping is None else alias_mapping
    kwargs = cbook.normalize_kwargs(kwargs, alias_mapping=alias_mapping)
    for key in set(drop) & set(kwargs.keys()):
        kwargs.pop(key)
    return kwargs


def set_colors(c, fc, ec, cmap):
    """Navigate interplay between possible color inputs {c, fc, ec, cmap}."""
    if fc in [None, 'None', 'none']:
        # unfilled contours
        if ec is None and cmap is None:
            cmap = basic_cmap(c)
    else:
        # filled contours
        if fc is True:
            fc = c
        if ec is None and cmap is None:
            ec = c
            cmap = basic_cmap(fc)
        elif ec is None:
            ec = (cmap(1.),)
        elif cmap is None:
            cmap = basic_cmap(fc)
    return fc, ec, cmap
