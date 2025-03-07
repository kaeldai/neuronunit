import inspect
from types import MethodType

import quantities as pq
from quantities.quantity import Quantity
import numpy as np
import matplotlib.pyplot as plt

import sciunit
import sciunit.scores as scores

import neuronunit.capabilities as cap
#import neuronunit.capabilities.spike_functions as sf
from neuronunit import neuroelectro
from .channel import *

class VmTest(sciunit.Test):
	"""Base class for tests involving the membrane potential of a model."""

	def __init__(self,
				 observation={'mean':None,'std':None},
				 name=None,
				 params=None):

		self.params = params if params else self.params
		if name is None:
			name = self.__class__.name
		sciunit.Test.__init__(self,observation,name)
		cap = []
		for cls in self.__class__.__bases__:
			cap += cls.required_capabilities
		self.required_capabilities += tuple(cap)
		
	required_capabilities = (cap.ProducesMembranePotential,)
	
	name = ''
	
	units = pq.Dimensionless
	
	ephysprop_name = ''
	
	params = {}
	
	# Observation values with units.  
	united_observation_keys = ['value','mean','std'] 

	def validate_observation(self, observation, united_keys=['value','mean'], nonunited_keys=[]):
		try:
			assert type(observation) is dict
			assert any([key in observation for key in united_keys]) \
				or len(nonunited_keys)
			for key in united_keys:
				if key in observation:
					assert type(observation[key]) is Quantity
			for key in nonunited_keys:
				if key in observation:
					assert type(observation[key]) is not Quantity
		except Exception as e:
			key_str = 'and/or a '.join(['%s key' % key for key in united_keys])
			msg = ("Observation must be a dictionary with a %s and each key "
				   "must have units from the quantities package." % key_str)
			raise sciunit.ObservationError(msg)
		for key in united_keys:
			if key in observation:
				provided = observation[key].simplified.units
				required = self.units.simplified.units
				if provided != required: # Units don't match spec.  
					msg = ("Units of %s are required for %s but units of %s "
						   "were provided" % (required.dimensionality.__str__(),
											  key, 
											  provided.dimensionality.__str__())
						   )
					raise sciunit.ObservationError(msg) 

	def bind_score(self, score, model, observation, prediction):
		score.related_data['vm'] = model.get_membrane_potential()
		score.related_data['model_name'] = '%s_%s' % (model.name,self.name)
		
		def plot_vm(self,ax=None,ylim=(-80,20)):
			"""A plot method the score can use for convenience."""
			if ax is None:
				ax = plt.gca()
			vm = score.related_data['vm'].rescale('mV')
			ax.plot(vm.times,vm)
			ax.set_ylim(ylim)
			ax.set_xlabel('Time (s)')
			ax.set_ylabel('Vm (mV)')
		score.plot_vm = MethodType(plot_vm, score) # Bind to the score.  
		return score

	@classmethod
	def neuroelectro_summary_observation(cls, neuron):
		reference_data = neuroelectro.NeuroElectroSummary(
			neuron = neuron, # Neuron type lookup using the NeuroLex ID.  
			ephysprop = {'name': cls.ephysprop_name} # Ephys property name in the NeuroElectro ontology. 
			)
		reference_data.get_values() # Get and verify summary data from neuroelectro.org. 
		observation = {'mean': reference_data.mean*cls.units,
					   'std': reference_data.std*cls.units,
					   'n': reference_data.n}
		return observation


class InputResistanceTest(VmTest):
	"""Tests the input resistance of a cell."""
	
	required_capabilities = (cap.ReceivesCurrent,)

	name = "Input resistance test"

	description = ("A test of the input resistance of a cell.")

	score_type = scores.ZScore
	
	units = pq.ohm*1e6

	params = {'injected_current':
				{'amplitude':-10.0*pq.pA, 'delay':100*pq.ms, 
				 'duration':500*pq.ms}}
	
	ephysprop_name = 'Input Resistance'

	def generate_prediction(self, model, verbose=False):
		"""Implementation of sciunit.Test.generate_prediction."""
		model.inject_current(self.params['injected_current']) 
		vm = model.get_membrane_potential() 
		
		def get_segment(self,vm,start,finish):
			start = int((start/vm.sampling_period).simplified)
			finish = int((finish/vm.sampling_period).simplified)
			return vm[start:finish]

		i = self.params['injected_current']
		start, stop = -11*pq.ms, -1*pq.ms
		before = get_segment(self,vm,start+i['delay'],
									 stop+i['delay'])
		after = get_segment(self,vm,start+i['delay']+i['duration'],
									stop+i['delay']+i['duration'])
		r_in = (after.mean()-before.mean())/i['amplitude']

		# Put prediction in a form that compute_score() can use.  
		prediction = {'value':r_in.simplified}
		return prediction


class APWidthTest(VmTest):
	"""Tests the full widths of action potentials at their half-maximum."""
	
	required_capabilities = (cap.ProducesActionPotentials,)

	name = "AP width test"

	description = ("A test of the widths of action potentials "
				   "at half of their maximum height.")

	score_type = scores.ZScore
	
	units = pq.ms
	
	ephysprop_name = 'Spike Half-Width'

	def generate_prediction(self, model, verbose=False):
		"""Implementation of sciunit.Test.generate_prediction."""
		# Method implementation guaranteed by ProducesActionPotentials capability.
		model.rerun = True
		widths = model.get_AP_widths() 
		# Put prediction in a form that compute_score() can use.  
		prediction = {'mean':np.mean(widths) if len(widths) else None,
					  'std':np.std(widths) if len(widths) else None,
					  'n':len(widths)}
		return prediction

	def compute_score(self, observation, prediction, verbose=False):
		"""Implementation of sciunit.Test.score_prediction."""
		if prediction['n'] == 0:
			score = scores.InsufficientDataScore(None)
		else:
			score = super(APWidthTest,self).compute_score(observation,prediction)	
		return score


class InjectedCurrentAPWidthTest(APWidthTest):
	"""
	Tests the full widths of APs at their half-maximum 
	under current injection.
	"""

	required_capabilities = (cap.ReceivesCurrent,)

	params = {'injected_current':{'amplitude':100.0*pq.pA}}

	name = "Injected current AP width test"

	description = ("A test of the widths of action potentials "
				   "at half of their maximum height when current "
				   "is injected into cell.")

	def generate_prediction(self, model, verbose=False):
		model.inject_current(self.params['injected_current']) 
		return super(InjectedCurrentAPWidthTest,self).generate_prediction(model, verbose=verbose)


class APAmplitudeTest(VmTest):
	"""Tests the heights (peak amplitude) of action potentials."""
	
	required_capabilities = (cap.ProducesActionPotentials,)

	name = "AP amplitude test"

	description = ("A test of the heights (peak amplitude) of "
				   "action potentials.")

	score_type = scores.ZScore
	
	units = pq.mV
	
	ephysprop_name = 'Spike Amplitude'

	def generate_prediction(self, model, verbose=False):
		"""Implementation of sciunit.Test.generate_prediction."""
		# Method implementation guaranteed by ProducesActionPotentials capability.
		model.rerun = True
		heights = model.get_AP_amplitudes() 
		# Put prediction in a form that compute_score() can use.  
		prediction = {'mean':np.mean(heights) if len(heights) else None,
					  'std':np.std(heights) if len(heights) else None,
					  'n':len(heights)}
		return prediction

	def compute_score(self, observation, prediction, verbose=False):
		"""Implementation of sciunit.Test.score_prediction."""
		if prediction['n'] == 0:
			score = scores.InsufficientDataScore(None)
		else:
			score = super(APAmplitudeTest,self).compute_score(observation, 
												prediction, verbose=verbose)	
		return score


class InjectedCurrentAPAmplitudeTest(APAmplitudeTest):
	"""
	Tests the heights (peak amplitude) of action potentials 
	under current injection.
	"""

	required_capabilities = (cap.ReceivesCurrent,)

	params = {'injected_current':{'amplitude':100.0*pq.pA}}

	name = "Injected current AP amplitude test"

	description = ("A test of the heights (peak amplitudes) of "
				   "action potentials when current "
				   "is injected into cell.")

	def generate_prediction(self, model, verbose=False):
		model.inject_current(self.params['injected_current']) 
		return super(InjectedCurrentAPAmplitudeTest,self).generate_prediction(model, verbose=verbose)


class RheobaseTest(VmTest):
	"""
	Tests the full widths of APs at their half-maximum 
	under current injection.
	"""

	required_capabilities = (cap.ReceivesCurrent,
							 cap.ProducesSpikes)

	params = {'injected_current':{'amplitude':0.0*pq.pA}}

	name = "Rheobase test"

	description = ("A test of the rheobase, i.e. the minimum injected current "
				   "needed to evoke at least one spike.")

	units = pq.pA

	score_type = scores.RatioScore
		
	def generate_prediction(self, model, verbose=False):
		"""Implementation of sciunit.Test.generate_prediction."""
		# Method implementation guaranteed by ProducesActionPotentials capability.
		prediction = {'value': None}
		model.rerun = True
		units = self.observation['value'].units

		lookup = self.threshold_FI(model, units)
		sub = np.array([x for x in lookup if lookup[x]==0])*units
		supra = np.array([x for x in lookup if lookup[x]>0])*units
			
		if verbose:
			if len(sub):
				print("Highest subthreshold current is %s" \
					  % (float(sub.max().round(2))*units))
			else:
				print("No subthreshold current was tested.")
			if len(supra):
				print("Lowest suprathreshold current is %s" \
					  % supra.min().round(2))
			else:
				print("No suprathreshold current was tested.")
				
		if len(sub) and len(supra):
			rheobase = supra.min()
		else:
			rheobase = None
		prediction['value'] = rheobase

		return prediction

	def threshold_FI(self, model, units, guess=None):
		lookup = {} # A lookup table global to the function below.  
		
		def f(ampl):
			if float(ampl) not in lookup:
				model.inject_current({'amplitude':ampl}) 
				n_spikes = model.get_spike_count()
				print("Injected %s current and got %d spikes" % (ampl,n_spikes))
				lookup[float(ampl)] = n_spikes

		max_iters = 10
		f(0.0*units)
		if guess is None:
			try:
				guess = self.observation['value']
			except KeyError:
				guess = 100*pq.pA
		high = guess*2
		high = (50.0*pq.pA).rescale(units) if not high else high 
		small = (1*pq.pA).rescale(units)
		f(high)
		i = 0

		while True:
			sub = np.array([x for x in lookup if lookup[x]==0])*units
			supra = np.array([x for x in lookup if lookup[x]>0])*units
			if i >= max_iters:
				break
			if len(sub) and len(supra):
				f((supra.min() + sub.max())/2)
			elif len(sub):
				f(max(small,sub.max()*2))
			elif len(supra):
				f(min(-small,supra.min()*2))
			i += 1

		return lookup

	def compute_score(self, observation, prediction, verbose=False):
		"""Implementation of sciunit.Test.score_prediction."""
		#print("%s: Observation = %s, Prediction = %s" % \
		#	 (self.name,str(observation),str(prediction)))
		if prediction['value'] is None:
			score = scores.InsufficientDataScore(None)
		else:
			score = super(RheobaseTest,self).compute_score(observation, prediction, verbose=verbose)	
		return score


class RestingPotentialTest(VmTest):
	"""Tests the resting potential under zero current injection."""
	
	required_capabilities = (cap.ReceivesCurrent,)

	name = "Resting potential test"

	description = ("A test of the resting potential of a cell "
				   "where injected current is set to zero.")

	score_type = scores.ZScore

	units = pq.mV
	
	ephysprop_name = 'Resting membrane potential'

	def validate_observation(self, observation):
		try:
			assert type(observation['mean']) is Quantity
			assert type(observation['std']) is Quantity
		except Exception as e:
			raise sciunit.ObservationError(("Observation must be of the form "
									"{'mean':float*mV,'std':float*mV}")) 

	def generate_prediction(self, model, verbose=False):
		"""Implementation of sciunit.Test.generate_prediction."""
		model.rerun = True
		model.inject_current({'amplitude':0.0*pq.pA}) 
		median = model.get_median_vm() # Use median instead of mean for robustness.  
		std = model.get_std_vm()
		prediction = {'mean':median, 'std':std}
		return prediction
