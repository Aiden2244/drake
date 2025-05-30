# -*- coding: utf-8 -*-

import copy
import gc
import sys
from types import SimpleNamespace
import unittest
import warnings
import weakref

import numpy as np

from pydrake.autodiffutils import AutoDiffXd
from pydrake.common.test_utilities.deprecation import catch_drake_warnings
from pydrake.common.value import Value
from pydrake.symbolic import Expression
from pydrake.systems.analysis import (
    Simulator,
    )
from pydrake.systems.framework import (
    AbstractParameterIndex,
    AbstractStateIndex,
    BasicVector, BasicVector_,
    CacheEntry,
    CacheEntryValue,
    CacheIndex,
    Context,
    ContinuousState_,
    ContinuousStateIndex,
    DependencyTicket,
    Diagram,
    DiagramBuilder,
    DiagramBuilder_,
    DiscreteStateIndex,
    DiscreteValues,
    EventStatus,
    InputPortIndex,
    LeafSystem, LeafSystem_,
    NumericParameterIndex,
    PortDataType,
    PublishEvent,
    State,
    System,
    TriggerType,
    UnrestrictedUpdateEvent,
    ValueProducer,
    VectorSystem,
    WitnessFunctionDirection,
    kUseDefaultName,
    )
from pydrake.systems.primitives import (
    Adder,
    ZeroOrderHold,
    )

from pydrake.systems.test.test_util import (
    call_leaf_system_overrides,
    call_vector_system_overrides,
    )

from pydrake.common.test_utilities import numpy_compare


def noop(*args, **kwargs):
    # When a callback is required for an interface, but not useful for testing.
    pass


class CustomAdder(LeafSystem):
    # Reimplements `Adder`.
    def __init__(self, num_inputs, size):
        LeafSystem.__init__(self)
        for i in range(num_inputs):
            self.DeclareVectorInputPort(
                "input{}".format(i), size)
        self.DeclareVectorOutputPort("sum", size, self._calc_sum)

    def _calc_sum(self, context, sum_data):
        # @note This will NOT work if the scalar type is AutoDiff or symbolic,
        # since they are not stored densely.
        sum = sum_data.get_mutable_value()
        sum[:] = 0
        for i in range(context.num_input_ports()):
            input_vector = self.EvalVectorInput(context=context, port_index=i)
            sum += input_vector.get_value()

    def DoGetGraphvizFragment(self, params):
        # N.B. We cannot use `header_lines.append(...)` here; the property
        # getter returns a _copy_ of the lines, not a _reference_.
        params.header_lines += ["hello=world"]
        params.options |= {"split": "I/O"}
        return super().DoGetGraphvizFragment(params)


# TODO(eric.cousineau): Make this class work with custom scalar types once
# referencing with custom dtypes lands.
# WARNING: At present, dtype=object matrices are NOT well supported, and may
# produce unexpected results (e.g. references not actually being respected).


class CustomVectorSystem(VectorSystem):
    def __init__(self, is_discrete):
        # VectorSystem only supports pure Continuous or pure Discrete.
        # Dimensions:
        #   1 Input, 2 States, 3 Outputs.
        VectorSystem.__init__(self, 1, 3, direct_feedthrough=True)
        self._is_discrete = is_discrete
        if self._is_discrete:
            self.DeclareDiscreteState(2)
        else:
            self.DeclareContinuousState(2)
        # Record calls for testing.
        self.has_called = []

    def DoCalcVectorOutput(self, context, u, x, y):
        self.ValidateContext(context=context)
        y[:] = np.hstack([u, x])
        self.has_called.append("output")

    def DoCalcVectorTimeDerivatives(self, context, u, x, x_dot):
        self.ValidateContext(context)
        x_dot[:] = x + u
        self.has_called.append("continuous")

    def DoCalcVectorDiscreteVariableUpdates(self, context, u, x, x_n):
        self.ValidateContext(context)
        x_n[:] = x + 2*u
        self.has_called.append("discrete")


class CustomPortsLifetimeHazardSystem(LeafSystem):
    # Save returned port references from all Declare*Port APIs to ensure none
    # of them induce the immortality hazard of #22515.
    def __init__(self):
        LeafSystem.__init__(self)

        # Declare some bogus state to allow later port declarations.
        self.DeclareContinuousState(1)
        self.DeclareDiscreteState(BasicVector(1))
        self.DeclareAbstractState(Value[str]())

        # Use all of the entry points that return port references, storing the
        # results in self.
        ports = set()
        ports.add(self.DeclareInputPort(kUseDefaultName,
                                        PortDataType.kVectorValued, 1))
        ports.add(self.DeclareAbstractInputPort("Ain", Value[str]()))
        ports.add(self.DeclareAbstractOutputPort("Aout",
                                                 lambda: Value(""),
                                                 lambda: Value("")))
        ports.add(self.DeclareVectorInputPort("Vin", 2))
        ports.add(self.DeclareVectorInputPort("Vin.rand", 2, random_type=None))
        ports.add(self.DeclareVectorOutputPort("Vout.size", 2, lambda: [1, 2]))
        ports.add(self.DeclareVectorOutputPort("Vout.model", BasicVector(2),
                                               lambda: [1, 2]))
        ports.add(self.DeclareStateOutputPort(kUseDefaultName,
                                              ContinuousStateIndex(0)))
        ports.add(self.DeclareStateOutputPort(kUseDefaultName,
                                              DiscreteStateIndex(0)))
        ports.add(self.DeclareStateOutputPort(kUseDefaultName,
                                              AbstractStateIndex(0)))
        self._ports = ports


# Wraps `Adder`.
class CustomDiagram(Diagram):
    # N.B. The CustomDiagram is used to unit test the DiagramBuilder.BuildInto
    # method.  For pydrake users, this is not a good example.  The best way in
    # pydrake to create a Diagram is DiagramBuilder.Build (as seen in the test
    # case named test_adder_simulation).

    def __init__(self, num_inputs, size):
        Diagram.__init__(self)
        builder = DiagramBuilder()
        adder = Adder(num_inputs, size)
        builder.AddSystem(adder)
        builder.ExportOutput(adder.get_output_port(0))
        for i in range(num_inputs):
            builder.ExportInput(adder.get_input_port(i))
        builder.BuildInto(self)

    def DoGetGraphvizFragment(self, params):
        # N.B. We cannot use `header_lines.append(...)` here; the property
        # getter returns a _copy_ of the lines, not a _reference_.
        params.header_lines += ["meaning_of_life=42"]
        return super().DoGetGraphvizFragment(params)


class TestCustom(unittest.TestCase):
    def _create_adder_system(self):
        system = CustomAdder(2, 3)
        return system

    def _fix_adder_inputs(self, system, context):
        self.assertEqual(context.num_input_ports(), 2)
        system.get_input_port(0).FixValue(context, [1, 2, 3])
        system.get_input_port(1).FixValue(context, [4, 5, 6])

    def test_diagram_adder(self):
        system = CustomDiagram(2, 3)
        self.assertEqual(system.GetSystemType(), f"{__name__}.CustomDiagram")
        self.assertEqual(system.num_input_ports(), 2)
        self.assertEqual(system.get_input_port(0).size(), 3)
        self.assertEqual(system.num_output_ports(), 1)
        self.assertEqual(system.get_output_port(0).size(), 3)

    def test_adder_execution(self):
        system = self._create_adder_system()
        self.assertEqual(system.GetSystemType(), f"{__name__}.CustomAdder")
        context = system.CreateDefaultContext()
        self.assertEqual(context.num_output_ports(), 1)
        self._fix_adder_inputs(system, context)
        output = system.AllocateOutput()
        self.assertEqual(output.num_ports(), 1)
        system.CalcOutput(context, output)
        value = output.get_vector_data(0).get_value()
        self.assertTrue(np.allclose([5, 7, 9], value))

    def test_adder_simulation(self):
        builder = DiagramBuilder()
        adder = builder.AddSystem(self._create_adder_system())
        adder.set_name("custom_adder")
        # Add ZOH so we can easily extract state.
        zoh = builder.AddSystem(ZeroOrderHold(0.1, 3))
        zoh.set_name("zoh")

        builder.ExportInput(adder.get_input_port(0))
        builder.ExportInput(adder.get_input_port(1))
        builder.Connect(adder.get_output_port(0), zoh.get_input_port(0))
        diagram = builder.Build()
        context = diagram.CreateDefaultContext()
        self._fix_adder_inputs(diagram, context)

        simulator = Simulator(diagram, context)
        simulator.Initialize()
        simulator.AdvanceTo(1)
        # Ensure that we have the outputs we want.
        value = (diagram.GetMutableSubsystemContext(zoh, context)
                 .get_discrete_state_vector().get_value())
        self.assertTrue(np.allclose([5, 7, 9], value))

    def test_adder_graphviz(self):
        system = CustomAdder(2, 3)
        graph = system.GetGraphvizString()
        self.assertIn("hello=world", graph)
        self.assertIn("(split)", graph)

    def test_diagram_graphviz(self):
        system = CustomDiagram(2, 3)
        graph = system.GetGraphvizString()
        self.assertIn("meaning_of_life=42", graph)

    def test_leaf_system_well_known_tickets(self):
        for func in [
                LeafSystem.accuracy_ticket,
                LeafSystem.all_input_ports_ticket,
                LeafSystem.all_parameters_ticket,
                LeafSystem.all_sources_except_input_ports_ticket,
                LeafSystem.all_sources_ticket,
                LeafSystem.all_state_ticket,
                LeafSystem.configuration_ticket,
                LeafSystem.ke_ticket,
                LeafSystem.kinematics_ticket,
                LeafSystem.nothing_ticket,
                LeafSystem.pa_ticket,
                LeafSystem.pc_ticket,
                LeafSystem.pe_ticket,
                LeafSystem.pn_ticket,
                LeafSystem.pnc_ticket,
                LeafSystem.q_ticket,
                LeafSystem.time_ticket,
                LeafSystem.v_ticket,
                LeafSystem.xa_ticket,
                LeafSystem.xc_ticket,
                LeafSystem.xcdot_ticket,
                LeafSystem.xd_ticket,
                LeafSystem.z_ticket]:
            self.assertIsInstance(func(), DependencyTicket, func)

    def test_leaf_system_per_item_tickets(self):
        dut = LeafSystem()
        dut.DeclareAbstractParameter(model_value=Value(1))
        dut.DeclareAbstractState(model_value=Value(1))
        dut.DeclareDiscreteState(1)
        dut.DeclareVectorInputPort("u0", BasicVector(1))
        self.assertEqual(dut.DeclareVectorInputPort("u1", 2).size(), 2)
        dut.DeclareNumericParameter(model_vector=BasicVector(1))
        for func, arg in [
                (dut.abstract_parameter_ticket, AbstractParameterIndex(0)),
                (dut.abstract_state_ticket, AbstractStateIndex(0)),
                (dut.cache_entry_ticket, CacheIndex(0)),
                (dut.discrete_state_ticket, DiscreteStateIndex(0)),
                (dut.input_port_ticket, InputPortIndex(0)),
                (dut.numeric_parameter_ticket, NumericParameterIndex(0)),
                ]:
            self.assertIsInstance(func(arg), DependencyTicket, func)

    def test_cache_entry(self):
        """Checks the existence of CacheEntry-related bindings."""

        # Cover DeclareCacheEntry.
        dummy = LeafSystem()
        model_value = Value(SimpleNamespace())

        def calc_cache(context, abstract_value):
            cache = abstract_value.get_mutable_value()
            self.assertIsInstance(cache, SimpleNamespace)
            cache.updated = True

        cache_entry = dummy.DeclareCacheEntry(
            description="scratch",
            value_producer=ValueProducer(
                allocate=model_value.Clone,
                calc=calc_cache),
            prerequisites_of_calc={dummy.nothing_ticket()})
        self.assertIsInstance(cache_entry, CacheEntry)

        context = dummy.CreateDefaultContext()

        # Cover CacheEntry and get_cache_entry.
        self.assertIsInstance(cache_entry.prerequisites(), set)
        self.assertTrue(cache_entry.is_out_of_date(context))
        self.assertFalse(cache_entry.is_cache_entry_disabled(context))
        cache_entry.disable_caching(context)
        self.assertTrue(cache_entry.is_cache_entry_disabled(context))
        cache_entry.enable_caching(context)
        self.assertFalse(cache_entry.is_cache_entry_disabled(context))
        self.assertFalse(cache_entry.is_disabled_by_default())
        cache_entry.disable_caching_by_default()
        self.assertTrue(cache_entry.is_disabled_by_default())
        self.assertIsInstance(cache_entry.description(), str)
        cache_index = cache_entry.cache_index()
        self.assertIsInstance(cache_index, CacheIndex)
        self.assertIsInstance(cache_entry.ticket(), DependencyTicket)
        self.assertIs(dummy.get_cache_entry(cache_index), cache_entry)
        self.assertFalse(cache_entry.has_default_prerequisites())

        # Cover CacheEntryValue.
        # WARNING: This is not the suggested workflow for proper bindings. See
        # below for proper workflow using .Eval().
        cache_entry_value = cache_entry.get_mutable_cache_entry_value(context)
        self.assertIsInstance(cache_entry_value, CacheEntryValue)
        data = cache_entry_value.GetMutableValueOrThrow()
        self.assertIsInstance(data, SimpleNamespace)
        # This has not yet been updated.
        self.assertFalse(hasattr(data, "updated"))
        # Const flavor access.
        cache_entry_value_const = cache_entry.get_cache_entry_value(context)
        self.assertIs(cache_entry_value_const, cache_entry_value)
        # Const flavor is out of date.
        with self.assertRaises(RuntimeError) as cm:
            cache_entry_value_const.GetValueOrThrow()
        self.assertIn("the current value is out of date", str(cm.exception))

        # Now properly update the cache entry.
        # Using .Eval() is the best workflow to follow.
        data_updated = cache_entry.Eval(context)
        # Ensure we didn't clone.
        self.assertIs(data, data_updated)
        # Mutated!
        self.assertTrue(data.updated)
        # Check abstract access.
        self.assertIs(cache_entry.EvalAbstract(context).get_value(), data)
        # Now check const aliasing.
        data_const = cache_entry_value_const.GetValueOrThrow()
        self.assertIs(data_const, data)

    def test_value_producer_error_reporting_allocate_none(self):
        def broken_alloc_callback():
            pass
        system = LeafSystem()
        cache_entry = system.DeclareCacheEntry(
            description="",
            value_producer=ValueProducer(
                allocate=broken_alloc_callback,
                calc=lambda context, output: None))
        with self.assertRaisesRegex(
                RuntimeError,
                "broken_alloc_callback.*Value.*not None"):
            system.CreateDefaultContext()

    def test_value_producer_error_reporting_allocate_mistyped(self):
        def broken_alloc_callback():
            return "hello"
        system = LeafSystem()
        cache_entry = system.DeclareCacheEntry(
            description="",
            value_producer=ValueProducer(
                allocate=broken_alloc_callback,
                calc=lambda context, output: None))
        with self.assertRaisesRegex(
                RuntimeError,
                "broken_alloc_callback.*return.*Value.*not.*str"):
            system.CreateDefaultContext()

    def test_leaf_system_issue13792(self):
        """
        Ensures that users get a better error when forgetting to explicitly
        call the C++ superclass's __init__.
        """

        class Oops(LeafSystem):
            def __init__(self):
                pass

        with self.assertRaisesRegex(TypeError, "LeafSystem.*__init__"):
            Oops()

    def test_all_leaf_system_overrides(self):
        test = self

        class TrivialSystem(LeafSystem):
            def __init__(self):
                LeafSystem.__init__(self)
                self.called_continuous = False
                self.called_initialize = False
                self.called_per_step = False
                self.called_periodic = False
                self.called_initialize_publish = False
                self.called_initialize_discrete = False
                self.called_initialize_unrestricted = False
                self.called_periodic_publish = False
                self.called_periodic_discrete = False
                self.called_periodic_unrestricted = False
                self.called_per_step_publish = False
                self.called_per_step_discrete = False
                self.called_per_step_unrestricted = False
                self.called_forced_publish = False
                self.called_forced_discrete = False
                self.called_forced_unrestricted = False
                self.called_getwitness = False
                self.called_witness = False
                self.called_guard = False
                self.called_reset = False
                self.called_system_reset = False
                # Ensure we have desired overloads.
                self.DeclareInitializationPublishEvent(
                    publish=self._on_initialize_publish)
                self.DeclareInitializationDiscreteUpdateEvent(
                    update=self._on_initialize_discrete)
                self.DeclareInitializationUnrestrictedUpdateEvent(
                    update=self._on_initialize_unrestricted)
                self.DeclareInitializationEvent(
                    event=PublishEvent(
                        trigger_type=TriggerType.kInitialization,
                        callback=self._on_initialize))
                self.DeclarePeriodicPublishEvent(
                    period_sec=1.0,
                    offset_sec=0,
                    publish=self._on_periodic_publish)
                self.DeclarePeriodicDiscreteUpdateEvent(
                    period_sec=1.0,
                    offset_sec=0,
                    update=self._on_periodic_discrete)
                self.DeclarePeriodicUnrestrictedUpdateEvent(
                    period_sec=1.0,
                    offset_sec=0,
                    update=self._on_periodic_unrestricted)
                self.DeclarePerStepPublishEvent(
                    publish=self._on_per_step_publish)
                self.DeclarePerStepDiscreteUpdateEvent(
                    update=self._on_per_step_discrete)
                self.DeclarePerStepUnrestrictedUpdateEvent(
                    update=self._on_per_step_unrestricted)
                self.DeclarePerStepEvent(
                    event=PublishEvent(
                        trigger_type=TriggerType.kPerStep,
                        callback=self._on_per_step))
                self.DeclareForcedPublishEvent(
                    publish=self._on_forced_publish)
                self.DeclareForcedDiscreteUpdateEvent(
                    update=self._on_forced_discrete)
                self.DeclareForcedUnrestrictedUpdateEvent(
                    update=self._on_forced_unrestricted)
                self.DeclarePeriodicEvent(
                    period_sec=1.0,
                    offset_sec=0.0,
                    event=PublishEvent(
                        trigger_type=TriggerType.kPeriodic,
                        callback=self._on_periodic))
                self.DeclareContinuousState(2)
                self.DeclareDiscreteState(1)
                # Ensure that we have inputs / outputs to call direct
                # feedthrough.
                self.DeclareInputPort(
                    kUseDefaultName, PortDataType.kVectorValued, 1)
                self.DeclareVectorInputPort(
                    name="test_input", model_vector=BasicVector(1),
                    random_type=None)
                self.DeclareVectorOutputPort(
                    "noop", BasicVector(1), noop,
                    prerequisites_of_calc=set([self.nothing_ticket()]))
                self.DeclareVectorOutputPort("noop2",
                                             1,
                                             noop,
                                             prerequisites_of_calc=set(
                                                 [self.nothing_ticket()]))
                self.witness = self.MakeWitnessFunction(
                    "witness", WitnessFunctionDirection.kCrossesZero,
                    self._witness)
                # Test bindings for both callback function signatures.
                self.reset_witness = self.MakeWitnessFunction(
                    "reset", WitnessFunctionDirection.kCrossesZero,
                    self._guard, UnrestrictedUpdateEvent(self._reset))
                self.system_reset_witness = self.MakeWitnessFunction(
                    "system reset", WitnessFunctionDirection.kCrossesZero,
                    self._guard, UnrestrictedUpdateEvent(
                        system_callback=self._system_reset))
                self.witness_result = 1.0
                self.getwitness_result = [
                    self.witness,
                    self.reset_witness,
                    self.system_reset_witness,
                ]

            def DoCalcTimeDerivatives(self, context, derivatives):
                # Note:  Don't call base method here; it would abort because
                # derivatives.size() != 0.
                test.assertEqual(derivatives.get_vector().size(), 2)
                self.called_continuous = True

            def DoGetWitnessFunctions(self, context):
                self.called_getwitness = True
                return self.getwitness_result

            def _on_initialize(self, context, event):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(event, PublishEvent)
                test.assertFalse(self.called_initialize)
                self.called_initialize = True

            def _on_per_step(self, context, event):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(event, PublishEvent)
                self.called_per_step = True

            def _on_periodic(self, context, event):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(event, PublishEvent)
                test.assertFalse(self.called_periodic)
                self.called_periodic = True

            def _on_initialize_publish(self, context):
                test.assertIsInstance(context, Context)
                test.assertFalse(self.called_initialize_publish)
                self.called_initialize_publish = True
                return EventStatus.Succeeded()

            def _on_initialize_discrete(self, context, discrete_state):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(discrete_state, DiscreteValues)
                test.assertFalse(self.called_initialize_discrete)
                self.called_initialize_discrete = True
                return EventStatus.Succeeded()

            def _on_initialize_unrestricted(self, context, state):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(state, State)
                test.assertFalse(self.called_initialize_unrestricted)
                self.called_initialize_unrestricted = True
                return EventStatus.Succeeded()

            def _on_periodic_publish(self, context):
                test.assertIsInstance(context, Context)
                test.assertFalse(self.called_periodic_publish)
                self.called_periodic_publish = True
                return EventStatus.Succeeded()

            def _on_periodic_discrete(self, context, discrete_state):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(discrete_state, DiscreteValues)
                test.assertFalse(self.called_periodic_discrete)
                self.called_periodic_discrete = True
                return EventStatus.Succeeded()

            def _on_periodic_unrestricted(self, context, state):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(state, State)
                test.assertFalse(self.called_periodic_unrestricted)
                self.called_periodic_unrestricted = True
                return EventStatus.Succeeded()

            def _on_per_step_publish(self, context):
                test.assertIsInstance(context, Context)
                self.called_per_step_publish = True
                return EventStatus.Succeeded()

            def _on_per_step_discrete(self, context, discrete_state):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(discrete_state, DiscreteValues)
                self.called_per_step_discrete = True
                return EventStatus.Succeeded()

            def _on_per_step_unrestricted(self, context, state):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(state, State)
                self.called_per_step_unrestricted = True
                return EventStatus.Succeeded()

            def _on_forced_publish(self, context):
                test.assertIsInstance(context, Context)
                test.assertFalse(self.called_forced_publish)
                self.called_forced_publish = True
                return EventStatus.Succeeded()

            def _on_forced_discrete(self, context, discrete_state):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(discrete_state, DiscreteValues)
                test.assertFalse(self.called_forced_discrete)
                self.called_forced_discrete = True
                return EventStatus.Succeeded()

            def _on_forced_unrestricted(self, context, state):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(state, State)
                test.assertFalse(self.called_forced_unrestricted)
                self.called_forced_unrestricted = True
                return EventStatus.Succeeded()

            def _witness(self, context):
                test.assertIsInstance(context, Context)
                self.called_witness = True
                return self.witness_result

            def _guard(self, context):
                test.assertIsInstance(context, Context)
                self.called_guard = True
                return context.get_time() - 0.5

            def _reset(self, context, event, state):
                test.assertIsInstance(context, Context)
                test.assertIsInstance(event, UnrestrictedUpdateEvent)
                test.assertIsInstance(state, State)
                self.called_reset = True

            def _system_reset(self, system, context, event, state):
                test.assertIsInstance(system, System)
                test.assertIsInstance(context, Context)
                test.assertIsInstance(event, UnrestrictedUpdateEvent)
                test.assertIsInstance(state, State)
                self.called_system_reset = True

        system = TrivialSystem()
        self.assertFalse(system.called_continuous)
        self.assertFalse(system.called_initialize)
        results = call_leaf_system_overrides(system)
        self.assertFalse(results["has_direct_feedthrough"])
        self.assertTrue(system.called_continuous)
        self.assertTrue(system.called_initialize)
        self.assertEqual(results["discrete_next_t"], 1.0)

        self.assertFalse(system.HasAnyDirectFeedthrough())
        self.assertFalse(system.HasDirectFeedthrough(output_port=0))
        self.assertFalse(
            system.HasDirectFeedthrough(input_port=0, output_port=0))

        # Test explicit calls.
        system = TrivialSystem()
        context = system.CreateDefaultContext()
        system.ForcedPublish(context=context)
        self.assertTrue(system.called_forced_publish)

        context_update = context.Clone()
        system.CalcTimeDerivatives(
            context=context,
            derivatives=context_update.get_mutable_continuous_state())
        self.assertTrue(system.called_continuous)

        system.called_continuous = False
        residual = system.AllocateImplicitTimeDerivativesResidual()
        system.CalcImplicitTimeDerivativesResidual(
            context=context,
            proposed_derivatives=context_update.get_continuous_state(),
            residual=residual)
        np.testing.assert_allclose(residual, 0, 1e-14)
        self.assertTrue(system.called_continuous)
        np.testing.assert_allclose(
            system.CalcImplicitTimeDerivativesResidual(
                context=context,
                proposed_derivatives=context_update.get_continuous_state()), 0,
            1e-14)

        witnesses = system.GetWitnessFunctions(context)
        self.assertEqual(len(witnesses), 3)

        system.CalcForcedDiscreteVariableUpdate(
            context=context,
            discrete_state=context_update.get_mutable_discrete_state())
        self.assertTrue(system.called_forced_discrete)

        system.CalcForcedUnrestrictedUpdate(
            context=context,
            state=context_update.get_mutable_state()
        )
        self.assertTrue(system.called_forced_unrestricted)

        # Test per-step, periodic, and witness call backs
        system = TrivialSystem()
        simulator = Simulator(system)
        simulator.get_mutable_context().SetAccuracy(0.1)
        # Stepping to 0.99 so that we get exactly one periodic event.
        simulator.AdvanceTo(0.99)
        self.assertTrue(system.called_per_step)
        self.assertTrue(system.called_periodic)
        self.assertTrue(system.called_initialize_publish)
        self.assertTrue(system.called_initialize_discrete)
        self.assertTrue(system.called_initialize_unrestricted)
        self.assertTrue(system.called_periodic_publish)
        self.assertTrue(system.called_periodic_discrete)
        self.assertTrue(system.called_periodic_unrestricted)
        self.assertTrue(system.called_per_step_publish)
        self.assertTrue(system.called_per_step_discrete)
        self.assertTrue(system.called_per_step_unrestricted)
        self.assertTrue(system.called_getwitness)
        self.assertTrue(system.called_witness)
        self.assertTrue(system.called_guard)
        self.assertTrue(system.called_reset)
        self.assertTrue(system.called_system_reset)

        # Test ExecuteInitializationEvents.
        system = TrivialSystem()
        context = system.CreateDefaultContext()
        system.ExecuteInitializationEvents(context=context)
        self.assertFalse(system.called_per_step)
        self.assertFalse(system.called_periodic)
        self.assertTrue(system.called_initialize_publish)
        self.assertTrue(system.called_initialize_discrete)
        self.assertTrue(system.called_initialize_unrestricted)
        self.assertFalse(system.called_periodic_publish)
        self.assertFalse(system.called_periodic_discrete)
        self.assertFalse(system.called_periodic_unrestricted)
        self.assertFalse(system.called_per_step_publish)
        self.assertFalse(system.called_per_step_discrete)
        self.assertFalse(system.called_per_step_unrestricted)
        self.assertFalse(system.called_getwitness)
        self.assertFalse(system.called_witness)
        self.assertFalse(system.called_guard)
        self.assertFalse(system.called_reset)
        self.assertFalse(system.called_system_reset)

        # Test ExecuteForcedEvents.
        system = TrivialSystem()
        context = system.CreateDefaultContext()
        system.ExecuteForcedEvents(context=context, publish=True)
        self.assertTrue(system.called_forced_publish)
        self.assertTrue(system.called_forced_discrete)
        self.assertTrue(system.called_forced_unrestricted)

        # Test witness function error messages.
        system = TrivialSystem()
        system.getwitness_result = None
        simulator = Simulator(system)
        with self.assertRaisesRegex(TypeError, "NoneType"):
            simulator.AdvanceTo(0.1)
        self.assertTrue(system.called_getwitness)
        system = TrivialSystem()
        system.witness_result = None
        simulator = Simulator(system)
        with self.assertRaisesRegex(TypeError, "NoneType"):
            simulator.AdvanceTo(0.1)
        self.assertTrue(system.called_witness)

    def test_event_handler_returns_none(self):
        """Checks that a Python event handler callback function is allowed to
        (implicitly) return None, instead of an EventStatus. Because of all the
        setup boilerplate, we only test one specific event type and assume that
        the other event types (which are implemented similarly) will likewise
        behave the same.
        """

        class PublishReturnsNoneSystem(LeafSystem):
            def __init__(self):
                LeafSystem.__init__(self)
                self.called_periodic_publish = False
                self.DeclarePeriodicPublishEvent(
                    period_sec=1.0, offset_sec=0.0,
                    publish=self._on_periodic_publish)

            def _on_periodic_publish(self, context):
                self.called_periodic_publish = True
                # There is no `return` statement here; Python implicitly treats
                # this like a `return None`.

        system = PublishReturnsNoneSystem()
        simulator = Simulator(system)
        simulator.AdvanceTo(0.25)
        self.assertTrue(system.called_periodic_publish)

    def test_state_output_port_declarations(self):
        """Checks that DeclareStateOutputPort is bound."""
        dut = LeafSystem()

        xc_index = dut.DeclareContinuousState(2)
        xc_port = dut.DeclareStateOutputPort(name="xc", state_index=xc_index)
        self.assertEqual(xc_port.size(), 2)

        xd_index = dut.DeclareDiscreteState(3)
        xd_port = dut.DeclareStateOutputPort(name="xd", state_index=xd_index)
        self.assertEqual(xd_port.size(), 3)

        xa_index = dut.DeclareAbstractState(Value(1))
        xa_port = dut.DeclareStateOutputPort(name="xa", state_index=xa_index)
        self.assertEqual(xa_port.get_name(), "xa")

    def test_vector_system_overrides(self):
        dt = 0.5
        for is_discrete in [False, True]:
            system = CustomVectorSystem(is_discrete)
            self.assertEqual(
                system.GetSystemType(), f"{__name__}.CustomVectorSystem")
            context = system.CreateDefaultContext()

            u = np.array([1.])
            system.get_input_port(0).FixValue(context, u)

            # Dispatch virtual calls from C++.
            output = call_vector_system_overrides(
                system, context, is_discrete, dt)
            self.assertTrue(system.HasAnyDirectFeedthrough())

            # Check call order.
            update_type = is_discrete and "discrete" or "continuous"
            self.assertEqual(
                system.has_called,
                [update_type, "output"])

            # Check values.
            state = context.get_state()
            x = (is_discrete and state.get_discrete_state()
                 or state.get_continuous_state()).get_vector().get_value()

            x0 = [0., 0.]
            c = is_discrete and 2 or 1*dt
            x_expected = x0 + c*u
            self.assertTrue(np.allclose(x, x_expected))

            # Check output.
            y_expected = np.hstack([u, x])
            y = output.get_vector_data(0).get_value()
            self.assertTrue(np.allclose(y, y_expected))

    def test_context_api(self):
        # Capture miscellaneous functions not yet tested.
        model_value = Value("Hello")
        model_vector = BasicVector([1., 2.])

        class TrivialSystem(LeafSystem):
            def __init__(self):
                LeafSystem.__init__(self)
                self.DeclareContinuousState(1)
                self.DeclareDiscreteState(2)
                self.DeclareAbstractState(model_value=model_value.Clone())
                self.DeclareAbstractParameter(model_value=model_value.Clone())
                self.DeclareNumericParameter(model_vector=model_vector.Clone())

        system = TrivialSystem()
        context = system.CreateDefaultContext()
        self.assertTrue(
            context.get_state() is context.get_mutable_state())
        self.assertEqual(context.num_continuous_states(), 1)
        self.assertTrue(
            context.get_continuous_state_vector() is
            context.get_mutable_continuous_state_vector())
        self.assertEqual(context.num_discrete_state_groups(), 1)
        self.assertTrue(
            context.get_discrete_state_vector() is
            context.get_mutable_discrete_state_vector())
        self.assertTrue(
            context.get_discrete_state(0) is
            context.get_discrete_state_vector())
        self.assertTrue(
            context.get_discrete_state(0) is
            context.get_discrete_state().get_vector(0))
        self.assertTrue(
            context.get_mutable_discrete_state(0) is
            context.get_mutable_discrete_state_vector())
        self.assertTrue(
            context.get_mutable_discrete_state(0) is
            context.get_mutable_discrete_state().get_vector(0))
        self.assertEqual(context.num_abstract_states(), 1)
        self.assertTrue(
            context.get_abstract_state() is
            context.get_mutable_abstract_state())
        self.assertTrue(
            context.get_abstract_state(0) is
            context.get_mutable_abstract_state(0))
        self.assertEqual(
            context.get_abstract_state(0).get_value(), model_value.get_value())

        # Check state API.
        state = context.get_mutable_state()
        self.assertTrue(
            state.get_mutable_discrete_state(index=0) is
            state.get_mutable_discrete_state().get_vector(index=0))
        self.assertTrue(
            state.get_abstract_state(index=0) is
            state.get_abstract_state().get_value(index=0))
        self.assertTrue(
            state.get_mutable_abstract_state(index=0) is
            state.get_mutable_abstract_state().get_value(index=0))

        # Check abstract state API (also test Values).
        values = context.get_abstract_state()
        self.assertEqual(values.size(), 1)
        self.assertEqual(
            values.get_value(0).get_value(), model_value.get_value())
        self.assertEqual(
            values.get_mutable_value(0).get_value(), model_value.get_value())
        values.SetFrom(values.Clone())

        # Check parameter accessors.
        self.assertEqual(system.num_abstract_parameters(), 1)
        self.assertEqual(
            context.get_abstract_parameter(index=0).get_value(),
            model_value.get_value())
        self.assertEqual(system.num_numeric_parameter_groups(), 1)
        np.testing.assert_equal(
            context.get_numeric_parameter(index=0).get_value(),
            model_vector.get_value())

        # Check diagram context accessors.
        builder = DiagramBuilder()
        builder.AddSystem(system)
        diagram = builder.Build()
        context = diagram.CreateDefaultContext()
        # Existence check.
        self.assertIsNot(
            diagram.GetMutableSubsystemState(system, context), None)
        subcontext = diagram.GetMutableSubsystemContext(subsystem=system,
                                                        context=context)
        self.assertIsNot(subcontext, None)
        self.assertIs(
            diagram.GetSubsystemContext(subsystem=system, context=context),
            subcontext)
        subcontext2 = system.GetMyMutableContextFromRoot(root_context=context)
        self.assertIsNot(subcontext2, None)
        self.assertIs(subcontext2, subcontext)
        self.assertIs(system.GetMyContextFromRoot(root_context=context),
                      subcontext2)

    def test_continuous_state_api(self):
        # N.B. Since this has trivial operations, we can test all scalar types.
        for T in [float, AutoDiffXd, Expression]:

            class TrivialSystem(LeafSystem_[T]):
                def __init__(self, index):
                    LeafSystem_[T].__init__(self)
                    num_q = 2
                    num_v = 1
                    num_z = 3
                    num_state = num_q + num_v + num_z
                    if index == 0:
                        self.DeclareContinuousState(
                            num_state_variables=num_state)
                    elif index == 1:
                        self.DeclareContinuousState(
                            num_q=num_q, num_v=num_v, num_z=num_z)
                    elif index == 2:
                        self.DeclareContinuousState(
                            BasicVector_[T](num_state))
                    elif index == 3:
                        self.DeclareContinuousState(
                            BasicVector_[T](num_state),
                            num_q=num_q, num_v=num_v, num_z=num_z)

                def DoCalcTimeDerivatives(self, context, derivatives):
                    derivatives.get_mutable_vector().SetZero()

            for index in range(4):
                system = TrivialSystem(index)
                context = system.CreateDefaultContext()
                self.assertEqual(
                    context.get_continuous_state_vector().size(), 6)
                self.assertEqual(system.AllocateTimeDerivatives().size(), 6)
                self.assertEqual(
                    system.EvalTimeDerivatives(context=context).size(), 6)

                # The constructors for ContinuousState(state: VectorBase, ...)
                # used when diagrams are in play receives special treatment in
                # the bindings for ContinuousState. We'll exercise it here.
                builder = DiagramBuilder_[T]()
                n = 2
                for _ in range(n):
                    builder.AddSystem(TrivialSystem(index))
                diagram = builder.Build()
                diagram_context = diagram.CreateDefaultContext()
                diagram_state_copy = ContinuousState_[T](
                    state=diagram_context.get_continuous_state().get_vector())
                self.assertEqual(diagram_state_copy.size(), 6*n)
                diagram_state_copy = ContinuousState_[T](
                    state=diagram_context.get_continuous_state().get_vector(),
                    num_q=2*n,
                    num_v=1*n,
                    num_z=3*n,
                )
                self.assertEqual(diagram_state_copy.num_q(), 2*n)
                self.assertEqual(diagram_state_copy.num_v(), 1*n)
                self.assertEqual(diagram_state_copy.num_z(), 3*n)
                self.assertEqual(diagram_state_copy.size(), 6*n)

    def test_discrete_state_api(self):
        # N.B. Since this has trivial operations, we can test all scalar types.
        for T in [float, AutoDiffXd, Expression]:

            class TrivialSystem(LeafSystem_[T]):
                def __init__(self, index):
                    LeafSystem_[T].__init__(self)
                    num_states = 3
                    if index == 0:
                        self.DeclareDiscreteState(
                            num_state_variables=num_states)
                    elif index == 1:
                        self.DeclareDiscreteState([1, 2, 3])
                    elif index == 2:
                        self.DeclareDiscreteState(
                            BasicVector_[T](num_states))

            for index in range(3):
                system = TrivialSystem(index)
                context = system.CreateDefaultContext()
                self.assertEqual(
                    context.get_discrete_state(0).size(), 3)
                self.assertEqual(system.AllocateDiscreteVariables().size(), 3)

    def test_abstract_io_port(self):
        test = self

        def assert_value_equal(a, b):
            a_name, a_value = a
            b_name, b_value = b
            self.assertEqual(a_name, b_name)
            numpy_compare.assert_equal(a_value, b_value)

        # N.B. Since this has trivial operations, we can test all scalar types.
        for T in [float, AutoDiffXd, Expression]:
            default_value = ("default", T(0.))
            expected_input_value = ("input", T(np.pi))
            expected_output_value = ("output", 2*T(np.pi))

            class CustomAbstractSystem(LeafSystem_[T]):
                def __init__(self):
                    LeafSystem_[T].__init__(self)
                    self.input_port = self.DeclareAbstractInputPort(
                        "in", Value(default_value))
                    self.output_port = self.DeclareAbstractOutputPort(
                        "out",
                        lambda: Value(default_value),
                        self.DoCalcAbstractOutput,
                        prerequisites_of_calc=set([
                            self.input_port.ticket()]))

                def DoCalcAbstractOutput(self, context, y_data):
                    input_value = self.EvalAbstractInput(
                        context=context, port_index=0).get_value()
                    # The allocator function will populate the output with
                    # the "input"
                    assert_value_equal(input_value, expected_input_value)
                    y_data.set_value(expected_output_value)
                    assert_value_equal(
                        y_data.get_value(), expected_output_value)

            system = CustomAbstractSystem()
            context = system.CreateDefaultContext()

            self.assertEqual(context.num_input_ports(), 1)
            system.get_input_port(0).FixValue(context, expected_input_value)
            output = system.AllocateOutput()
            self.assertEqual(output.num_ports(), 1)
            system.CalcOutput(context, output)
            value = output.get_data(0)
            self.assertEqual(value.get_value(), expected_output_value)

    def assert_equal_but_not_aliased(self, a, b):
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_context_and_value_object_set_from(self):
        """
        Shows how `Value[object]` behaves in a context, especially in
        connection to `Context.SetTimeStateAndParametersFrom()`.

        Helps to highlight failure mode illustrated in #18653.
        """
        arbitrary_object = {"key": "value"}

        class SystemWithCacheAndState(LeafSystem):
            def __init__(self):
                super().__init__()
                model_value = Value(arbitrary_object)
                self.state_index = self.DeclareAbstractState(model_value)

                def calc_cache_noop(context, abstract_value):
                    pass

                self.cache_entry = self.DeclareCacheEntry(
                    description="test",
                    value_producer=ValueProducer(
                        allocate=model_value.Clone,
                        calc=calc_cache_noop,
                    ),
                )

            def eval_state(self, context):
                return context.get_abstract_state(self.state_index).get_value()

        system = SystemWithCacheAndState()
        context = system.CreateDefaultContext()
        context_init = context.Clone()

        cache = system.cache_entry.Eval(context)
        self.assert_equal_but_not_aliased(cache, arbitrary_object)
        state = system.eval_state(context)
        self.assert_equal_but_not_aliased(state, arbitrary_object)

        def check_set_from():
            nonlocal cache, state
            context.SetTimeStateAndParametersFrom(context_init)
            # Ensure that we have cloned the object.
            old_state = state
            state = system.eval_state(context)
            self.assert_equal_but_not_aliased(state, old_state)
            # Warning: Cache objects are not cloned!
            old_cache = cache
            cache = system.cache_entry.Eval(context)
            self.assertIs(cache, old_cache)

        # Check twice. Per #18653, if we did not implement
        # Value[object].SetFrom() correctly, this would fail the second time.
        check_set_from()
        check_set_from()

    def test_ports_lifetime_hazard(self):
        # Test variants of the immortality hazard reported in #22515.
        dut = CustomPortsLifetimeHazardSystem()

        # Show that a system that saves its port references is mortal.
        spy = weakref.finalize(dut, lambda: None)
        del dut
        gc.collect()
        self.assertFalse(spy.alive)
