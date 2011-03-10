# -*- coding: utf-8 -*-
#
#% $Id$
#
#
# Copyright (C) 2002-2007
# The MeqTree Foundation &
# ASTRON (Netherlands Foundation for Research in Astronomy)
# P.O.Box 2, 7990 AA Dwingeloo, The Netherlands
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>,
# or write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
"""This implements a Jones module for WSRT beams.
  See also analytic_beams in Siamese.OMS for an alternative.
  The two modules will eventually be merged.
""";

from Timba.TDL import *
from Meow.Direction import radec_to_lmn
import Meow
from Meow import Context
from Meow import StdTrees
from Meow import ParmGroup

import math
from math import sqrt,atan2


import solvable_pointing_errors

DEG = math.pi/180.;
ARCMIN = DEG/60;
ARCSEC = DEG/3600;

def WSRT_cos3_beam (E,lm,bf,*dum):
  """computes a cos^3 beam for the given direction, using NEWSTAR's
  cos^^(fq*B*r) model (thus giving a cos^6 power beam).
  r=sqrt(l^2+m^2), which is not entirely accurate (in terms of angular distance), but close enough
  to be good for NEWSTAR, so good enough for us.
  'E' is output node
  'lm' is direction (2-vector node, or l,m tuple)
  """
  ns = E.Subscope();
  if isinstance(lm,(list,tuple)):
    l,m = lm;
    r = ns.r << sqrt(l*l+m*m);
  else:
    r = ns.r << Meq.Norm(lm);
  clip = wsrt_beam_clip;
  if wsrt_newstar_mode:
    clip = -clip;
  E << Meq.WSRTCos3Beam(bf,r,clip=clip);
  return E;

def compute_jones (Jones,sources,stations=None,label="beam",inspectors=[],
                   solvable_sources=set(),**kw):
  """Computes beam gain for a list of sources.
  The output node, will be qualified with either a source only, or a source/station pair
  """;
  stations = stations or Context.array.stations();
  ns = Jones.Subscope();

  if not make_solvable or not solve_shape:
    ns.beamscale << wsrt_beam_size_factor*1e-9;

  # this dict will hold LM tuples (or nodes) for each source.
  lmsrc = {};
  # see if sources have a "beam_lm" or "lm_ncp" attribute, use that for beam offsets
#  log = file("e.log","wt");
  for src in sources:
    lm = src.get_attr("beam_lm",None) or src.get_attr("_lm_ncp",None);
# STOOOOOPID: shouldn't use lm_ncp for WSRT beam, since that distorts the Y scale!!!
    if lm:
      l,m = lmsrc[src.name] = lm;
#      log.write("%s l=%.14g m=%.14g r=%.14g (from model)\n"
#                  %(src.name,l,m,sqrt(l*l+m*m)));
      src.set_attr(label+'r',math.sqrt(l**2+m**2)/math.pi*(180*60));
    # else try to use static lm coordinates
    else:
      # else try to use static lm coordinates
      lmnst = src.direction.lmn_static();
      if lmnst:
        l,m = lmsrc[src.name] = lmnst[0:2];
        src.set_attr(label+'r',math.sqrt(l**2+m**2)/math.pi*(180*60));
#        log.write("%s l=%.14g m=%.14g r=%.14g (computed)\n"
#                   %(src.name,l,m,sqrt(l*l+m*m)));
      # else use lmn node
      else:
        lmsrc[src.name] = src.direction.lm();

  # set of all sources, will later become set of sources for which
  # a beam hasn't been computed
  all_sources = set([src.name for src in sources]);

  # if pointing errors are enabled, compute beams for sources with a PE
  if make_solvable:
    parms = [];
    parmgroups = [];

    if solve_shape is BEAM_CIRCULAR:
      parmdef = Meq.Parm(wsrt_beam_size_factor*1e-9,tags="beam solvable");
      for p in stations:
        bf = ns.beamscale(p) << parmdef;
        parms.append(bf);
      parmsgroups.append(ParmGroup.Subgroup("beam shape",list(parms)));
    elif solve_shape is BEAM_POLARIZED:
      bf = ns.beamscale << wsrt_beam_size_factor*1e-9;
      parmdef = Meq.Parm(1,tags="beam solvable");
      for p in stations:
        for xy in "xy":
          bs = ns.beamshape(p,xy);
          for lm in "lm":
            parms.append(bs(lm) << parmdef);
          bs << Meq.Composer(*[bs(lm) for lm in "lm"]);
      parmgroups.append(ParmGroup.Subgroup("beam shape",list(parms)));
    # is a subset specified?
    pe_sources = [ src.name for src in _pe_subset_selector.filter(sources) ];
    all_sources -= set(pe_sources);
    # call the pointings module
    if solve_pointings:
      pparms = [];
      solvable_pointing_errors.compute_pointings(ns.dlm,stations,label=label+"pnt",return_parms=pparms);
      parmgroups.append(ParmGroup.Subgroup("pointing offsets",pparms));
      parms += pparms;
    # create nodes to compute actual pointing per source, per antenna
    for name in pe_sources:
      solvable_sources.add(name);
      lm = lmsrc[name];
      # if LM is a static constant still, make constant node for it
      if isinstance(lm,(list,tuple)):
        lm = ns.lm(name) << Meq.Constant(value=Timba.array.array(lm));
      for p in stations:
        Ej = Jones(name,p);
        # make offset lm
        if solve_pointings:
          lm1 = lm(p) << lm - ns.dlm(p);
        else:
          lm1 = lm;
        if solve_shape is BEAM_POLARIZED:
          WSRT_cos3_beam(Ej("x"),lm1/ns.beamshape(p,"x"),ns.beamscale);
          WSRT_cos3_beam(Ej("y"),lm1/ns.beamshape(p,"y"),ns.beamscale);
          Ej << Meq.Matrix22(Ej("x"),0,0,Ej("y"));
        elif solve_shape is BEAM_CIRCULAR:
          WSRT_cos3_beam(Ej,lm1,ns.beamscale(p));
        else:
          WSRT_cos3_beam(Ej,lm1,ns.beamscale);
    # add parameters
    if parms:
      global pg_beam;
      pg_beam = ParmGroup.ParmGroup(label,parms,subgroups=parmgroups,table_name="%s.fmep"%label,bookmark=True);
      ParmGroup.SolveJob("cal_"+label,"Calibrate beam parameters",pg_beam);
      global solvable;
      solvable = True;
    # make inspectors
    if solve_shape is BEAM_POLARIZED:
      inspectors.append(ns.inspector("shape") << StdTrees.define_inspector(
            ns.beamshape,stations,"xy",label=label));
    if solve_shape is BEAM_CIRCULAR:
      inspectors.append(ns.inspector("scale") << StdTrees.define_inspector(
            ns.beamscale,stations,label=label));
    if solve_pointings:
      inspectors.append(ns.inspector('dlm') << StdTrees.define_inspector(ns.dlm,stations,label=label));

    inspectors.append(ns.inspector << StdTrees.define_inspector(
            Jones,pe_sources,stations,label=label));

  # Now, all_sources is the set of sources for which we haven't computed the beam yet
  # (the ones that are not solvable, presumably.)
  for name in all_sources:
    b0 = Jones(name,stations[0]);
    WSRT_cos3_beam(b0,lmsrc[name],ns.beamscale);
    for p in stations[1:]:
      Jones(name,p) << Meq.Identity(b0);

  return Jones;



from Meow.MeqMaker import SourceSubsetSelector

# this will be set to True on a per-source basis, or if beam scale is solvable
solvable = False;

BEAM_CIRCULAR = "circular, unpolarized";
BEAM_POLARIZED = "elliptic, polarized";

_pe_subset_selector = SourceSubsetSelector("Apply to subset of sources",'wsrt_beams',annotate=False);
TDLCompileMenu("Enable solvable beam parameters",
  TDLOption("solve_pointings","Solve for pointing offsets",False),
  TDLOption("solve_shape","Solvable for beam shape",
          [None,BEAM_CIRCULAR,BEAM_POLARIZED]),
  toggle='make_solvable',
  *_pe_subset_selector.options);
TDLCompileOption('wsrt_beam_size_factor',"Beam scale factor (1/GHz)",[65.],more=float);
TDLCompileOption('wsrt_beam_clip',"Clip beam once gain goes below",[.1],more=float,
  doc="""This makes the beam flat outside the circle corresponding to the specified gain value.""");
TDLCompileOption('wsrt_newstar_mode',"Use NEWSTAR-compatible beam clipping (very naughty)",False,
  doc="""NEWSTAR's primary beam model does not implement clipping properly: it only makes the
  beam flat where the model gain goes below the threshold. Further away, where the gain (which
  is cos^3(r) essentially) rises above the threshold again, the beam is no longer clipped, and so
  the gain goes up again. This is a physically incorrect model, but you may need to enable this
  if working with NEWSTAR-derived models, since fluxes of far-off sources will have been estimated with
  this incorrect beam.""");

