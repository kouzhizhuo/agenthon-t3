import logging
import queue
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type
import numpy as np
import pandas as pd
from . import NanosecondTime
from .agent import Agent
from .message import Message, MessageBatch, WakeupMsg
from .latency_model import LatencyModel
from .utils import fmt_ts, str_to_ns
logger = logging.getLogger(__name__)

class Kernel:
    """
    ABIDES Kernel

    Arguments:
        agents: List of agents to include in the simulation.
        start_time: Timestamp giving the start time of the simulation.
        stop_time: Timestamp giving the end time of the simulation.
        default_computation_delay: time penalty applied to an agent each time it is
            awakened (wakeup or recvMsg).
        default_latency: latency imposed on each computation, modeled physical latency in systems and avoid infinite loop of events happening at the same exact time (in ns)
        agent_latency: legacy parameter, used when agent_latency_model is not defined
        latency_noise:legacy parameter, used when agent_latency_model is not defined
        agent_latency_model: Model of latency used for the network of agents.
        skip_log: if True, no log saved on disk.
        seed: seed of the simulation.
        log_dir: directory where data is store.
        custom_properties: Different attributes that can be added to the simulation
            (e.g., the oracle).
    """

    def __init__(self, agents: List[Agent], start_time: NanosecondTime=str_to_ns('09:30:00'), stop_time: NanosecondTime=str_to_ns('16:00:00'), default_computation_delay: int=1, default_latency: float=1, agent_latency: Optional[List[List[float]]]=None, latency_noise: List[float]=[1.0], agent_latency_model: Optional[LatencyModel]=None, skip_log: bool=True, seed: Optional[int]=None, log_dir: Optional[str]=None, custom_properties: Optional[Dict[str, Any]]=None, random_state: Optional[np.random.RandomState]=None) -> None:
        custom_properties = custom_properties or {}
        self.random_state: np.random.RandomState = random_state or np.random.RandomState(seed=np.random.randint(low=0, high=2 ** 32, dtype='uint64'))
        self.messages: queue.PriorityQueue[int, str, Message] = queue.PriorityQueue()
        self.kernel_wall_clock_start: datetime = datetime.now()
        self.mean_result_by_agent_type: Dict[str, Any] = {}
        self.agent_count_by_type: Dict[str, int] = {}
        self.summary_log: List[Dict[str, Any]] = []
        self.has_run = False
        for key, value in custom_properties.items():
            setattr(self, key, value)
        self.agents: List[Agent] = agents
        self.gym_agents: List[Agent] = list(filter(lambda agent: 'CoreGymAgent' in [c.__name__ for c in agent.__class__.__bases__], agents))
        assert len(self.gym_agents) <= 1, 'ABIDES-gym currently only supports using one gym agent'
        if logger.isEnabledFor(10):
            logger.debug(f'Detected {len(self.gym_agents)} ABIDES-gym agents')
        self.custom_state: Dict[str, Any] = {}
        self._msg_ledger: List[Dict[str, Any]] = []
        self._deliver_seq: int = 0
        self._deliver_seq_by_key: Dict[Tuple[int, int], int] = {}
        self._current_causal_uid: Optional[int] = None
        self.start_time: NanosecondTime = start_time
        self.stop_time: NanosecondTime = stop_time
        self.current_time: NanosecondTime = start_time
        self.seed: Optional[int] = seed
        self.skip_log: bool = skip_log
        self.log_dir: str = log_dir or str(int(self.kernel_wall_clock_start.timestamp()))
        self.agent_current_times: List[NanosecondTime] = [self.start_time] * len(self.agents)
        self.agent_computation_delays: List[int] = [default_computation_delay] * len(self.agents)
        self.agent_latency_model = agent_latency_model
        if agent_latency is None:
            self.agent_latency: List[List[float]] = [[default_latency] * len(self.agents)] * len(self.agents)
        else:
            self.agent_latency = agent_latency
        self.latency_noise: List[float] = latency_noise
        self.current_agent_additional_delay: int = 0
        self.show_trace_messages: bool = False
        if logger.isEnabledFor(10):
            logger.debug(f'Kernel initialized')

    def run(self) -> Dict[str, Any]:
        """
        Wrapper to run the entire simulation (when not running in ABIDES-Gym mode).

        3 Steps:
          - Simulation Instantiation
          - Simulation Run
          - Simulation Termination

        Returns:
            An object that contains all the objects at the end of the simulation.
        """
        self.initialize()
        self.runner()
        return self.terminate()

    def initialize(self) -> None:
        """
        Instantiation of the simulation:
          - Creation of the different object of the simulation.
          - Instantiation of the latency network
          - Calls on the kernel_initializing and KernelStarting of the different agents
        """
        if logger.isEnabledFor(10):
            logger.debug('Kernel started')
        if logger.isEnabledFor(10):
            logger.debug('Simulation started!')
        if logger.isEnabledFor(10):
            logger.debug('--- Agent.kernel_initializing() ---')
        for agent in self.agents:
            agent.kernel_initializing(self)
        if logger.isEnabledFor(10):
            logger.debug('--- Agent.kernel_starting() ---')
        for agent in self.agents:
            agent.kernel_starting(self.start_time)
        self.current_time = self.start_time
        if logger.isEnabledFor(10):
            logger.debug('--- Kernel Clock started ---')
        if logger.isEnabledFor(10):
            logger.debug('Kernel.current_time is now {}'.format(fmt_ts(self.current_time)))
        if logger.isEnabledFor(10):
            logger.debug('--- Kernel Event Queue begins ---')
        if logger.isEnabledFor(10):
            logger.debug('Kernel will start processing messages. Queue length: {}'.format(len(self.messages.queue)))
        self.event_queue_wall_clock_start = datetime.now()
        self.ttl_messages = 0

    def runner(self, agent_actions: Optional[Tuple[Agent, List[Dict[str, Any]]]]=None) -> Dict[str, Any]:
        """
        Start the simulation and processing of the message queue.
        Possibility to add the optional argument agent_actions. It is a list of dictionaries corresponding
        to actions to be performed by the experimental agent (Gym Agent).

        Arguments:
            agent_actions: A list of the different actions to be performed represented in a dictionary per action.

        Returns:
          - it is a dictionnary composed of two elements:
            - "done": boolean True if the simulation is done, else False. It is true when simulation reaches end_time or when the message queue is empty.
            - "results": it is the raw_state returned by the gym experimental agent, contains data that will be formated in the gym environement to formulate state, reward, info etc.. If
               there is no gym experimental agent, then it is None.
        """
        if agent_actions is not None:
            exp_agent, action_list = agent_actions
            exp_agent.apply_actions(action_list)
        while not self.messages.empty() and self.current_time and (self.current_time <= self.stop_time):
            self.current_time, event = self.messages.get()
            assert self.current_time is not None
            sender_id, recipient_id, message = event
            if self.ttl_messages % 100000 == 0:
                if logger.isEnabledFor(20):
                    logger.info('--- Simulation time: {}, messages processed: {:,}, wallclock elapsed: {:.2f}s ---'.format(fmt_ts(self.current_time), self.ttl_messages, (datetime.now() - self.event_queue_wall_clock_start).total_seconds()))
            if self.show_trace_messages:
                if logger.isEnabledFor(10):
                    logger.debug('--- Kernel Event Queue pop ---')
                if logger.isEnabledFor(10):
                    logger.debug('Kernel handling {} message for agent {} at time {}'.format(message.type(), recipient_id, self.current_time))
            self.ttl_messages += 1
            self.current_agent_additional_delay = 0
            if isinstance(message, WakeupMsg):
                if self.agent_current_times[recipient_id] > self.current_time:
                    self.messages.put((self.agent_current_times[recipient_id], (sender_id, recipient_id, message)))
                    if self.show_trace_messages:
                        if logger.isEnabledFor(10):
                            logger.debug('After wakeup return, agent {} delayed from {} to {}'.format(recipient_id, fmt_ts(self.current_time), fmt_ts(self.agent_current_times[recipient_id])))
                    continue
                self.agent_current_times[recipient_id] = self.current_time
                self._current_causal_uid = message.message_id
                self._deliver_seq_by_key[message.message_id, recipient_id] = self._deliver_seq
                self._deliver_seq += 1
                self._msg_ledger.append({'message_id': message.message_id, 'src_id': recipient_id, 'dst_id': recipient_id, 't_send_ns': None, 't_recv_ns': self.current_time, 'latency_ns': 0, 'msg_type': 'AGENT_WAKEUP', 'order_id': None, 'causal_parent': None})
                wakeup_result = self.agents[recipient_id].wakeup(self.current_time)
                self.agent_current_times[recipient_id] += self.agent_computation_delays[recipient_id] + self.current_agent_additional_delay
                if self.show_trace_messages:
                    if logger.isEnabledFor(10):
                        logger.debug('After wakeup return, agent {} delayed from {} to {}'.format(recipient_id, fmt_ts(self.current_time), fmt_ts(self.agent_current_times[recipient_id])))
                if wakeup_result != None:
                    return {'done': False, 'result': wakeup_result}
            else:
                if self.agent_current_times[recipient_id] > self.current_time:
                    self.messages.put((self.agent_current_times[recipient_id], (sender_id, recipient_id, message)))
                    if self.show_trace_messages:
                        if logger.isEnabledFor(10):
                            logger.debug('Agent in future: message requeued for {}'.format(fmt_ts(self.agent_current_times[recipient_id])))
                    continue
                self.agent_current_times[recipient_id] = self.current_time
                if isinstance(message, MessageBatch):
                    messages = message.messages
                else:
                    messages = [message]
                for message in messages:
                    self.agent_current_times[recipient_id] += self.agent_computation_delays[recipient_id] + self.current_agent_additional_delay
                    if self.show_trace_messages:
                        if logger.isEnabledFor(10):
                            logger.debug('After receive_message return, agent {} delayed from {} to {}'.format(recipient_id, fmt_ts(self.current_time), fmt_ts(self.agent_current_times[recipient_id])))
                    self._current_causal_uid = message.message_id
                    self._deliver_seq_by_key[message.message_id, recipient_id] = self._deliver_seq
                    self._deliver_seq += 1
                    self.agents[recipient_id].receive_message(self.current_time, sender_id, message)
        if self.messages.empty():
            if logger.isEnabledFor(10):
                logger.debug('--- Kernel Event Queue empty ---')
        if self.current_time and self.current_time > self.stop_time:
            if logger.isEnabledFor(10):
                logger.debug('--- Kernel Stop Time surpassed ---')
        if len(self.gym_agents) > 0:
            self.gym_agents[0].update_raw_state()
            return {'done': True, 'result': self.gym_agents[0].get_raw_state()}
        else:
            return {'done': True, 'result': None}

    def terminate(self) -> Dict[str, Any]:
        """
        Termination of the simulation. Called once the queue is empty, or the gym environement is done, or the simulation
        reached kernel stop time:
          - Calls the kernel_stopping of the agents
          - Calls the kernel_terminating of the agents

        Returns:
            custom_state: it is an object that contains everything in the simulation. In particular it is useful to retrieve agents and/or logs after the simulation to proceed to analysis.
        """
        event_queue_wall_clock_stop = datetime.now()
        event_queue_wall_clock_elapsed = event_queue_wall_clock_stop - self.event_queue_wall_clock_start
        if logger.isEnabledFor(10):
            logger.debug('--- Agent.kernel_stopping() ---')
        for agent in self.agents:
            agent.kernel_stopping()
        if logger.isEnabledFor(10):
            logger.debug('\n--- Agent.kernel_terminating() ---')
        for agent in self.agents:
            agent.kernel_terminating()
        if logger.isEnabledFor(20):
            logger.info('Event Queue elapsed: {}, messages: {:,}, messages per second: {:0.1f}'.format(event_queue_wall_clock_elapsed, self.ttl_messages, self.ttl_messages / event_queue_wall_clock_elapsed.total_seconds()))
        self.custom_state['kernel_event_queue_elapsed_wallclock'] = event_queue_wall_clock_elapsed
        self.custom_state['kernel_slowest_agent_finish_time'] = max(self.agent_current_times)
        self.custom_state['agents'] = self.agents
        self.custom_state['message_ledger'] = self._msg_ledger
        self.custom_state['deliver_seq_by_key'] = self._deliver_seq_by_key
        self.write_summary_log()
        if logger.isEnabledFor(20):
            logger.info('Mean ending value by agent type:')
        for a in self.mean_result_by_agent_type:
            value = self.mean_result_by_agent_type[a]
            count = self.agent_count_by_type[a]
            if logger.isEnabledFor(20):
                logger.info(f'{a}: {int(round(value / count)):d}')
        if logger.isEnabledFor(20):
            logger.info('Simulation ending!')
        return self.custom_state

    def reset(self) -> None:
        """
        Used in the gym core environment:
          - First calls termination of the kernel, to close previous simulation
          - Then initializes a new simulation
          - Then runs the simulation (not specifying any action this time).
        """
        if self.has_run:
            self.terminate()
        self.initialize()
        self.runner()

    def send_message(self, sender_id: int, recipient_id: int, message: Message, delay: int=0) -> None:
        """
        Called by an agent to send a message to another agent.

        The kernel supplies its own current_time (i.e. "now") to prevent possible abuse
        by agents. The kernel will handle computational delay penalties and/or network
        latency.

        Arguments:
            sender_id: ID of the agent sending the message.
            recipient_id: ID of the agent receiving the message.
            message: The ``Message`` class instance to send.
            delay: Represents an agent's request for ADDITIONAL delay (beyond the
                Kernel's mandatory computation + latency delays). Represents parallel
                pipeline processing delays (that should delay the transmission of
                messages but do not make the agent "busy" and unable to respond to new
                messages)
        """
        sent_time = self.current_time + self.agent_computation_delays[sender_id] + self.current_agent_additional_delay + delay
        if self.agent_latency_model is not None:
            latency: float = self.agent_latency_model.get_latency(sender_id=sender_id, recipient_id=recipient_id)
            deliver_at = sent_time + int(latency)
            if self.show_trace_messages:
                if logger.isEnabledFor(10):
                    logger.debug('Kernel applied latency {}, accumulated delay {}, one-time delay {} on send_message from: {} to {}, scheduled for {}'.format(latency, self.current_agent_additional_delay, delay, self.agents[sender_id].name, self.agents[recipient_id].name, fmt_ts(deliver_at)))
        else:
            latency = self.agent_latency[sender_id][recipient_id]
            noise = self.random_state.choice(len(self.latency_noise), p=self.latency_noise)
            deliver_at = sent_time + int(latency + noise)
            if self.show_trace_messages:
                if logger.isEnabledFor(10):
                    logger.debug('Kernel applied latency {}, noise {}, accumulated delay {}, one-time delay {} on send_message from: {} to {}, scheduled for {}'.format(latency, noise, self.current_agent_additional_delay, delay, self.agents[sender_id].name, self.agents[recipient_id].name, fmt_ts(deliver_at)))
        self.messages.put((deliver_at, (sender_id, recipient_id, message)))
        _ledger_msgs = message.messages if isinstance(message, MessageBatch) else [message]
        for _lm in _ledger_msgs:
            _ord = getattr(_lm, 'order', None)
            self._msg_ledger.append({'message_id': _lm.message_id, 'src_id': sender_id, 'dst_id': recipient_id, 't_send_ns': sent_time, 't_recv_ns': deliver_at, 'latency_ns': deliver_at - sent_time, 'msg_type': _lm.type(), 'order_id': getattr(_ord, 'order_id', None), 'causal_parent': self._current_causal_uid})
        if self.show_trace_messages:
            if logger.isEnabledFor(10):
                logger.debug('Sent time: {}, current time {}, computation delay {}'.format(sent_time, fmt_ts(self.current_time), self.agent_computation_delays[sender_id]))
            if logger.isEnabledFor(10):
                logger.debug('Message queued: {}'.format(message))

    def set_wakeup(self, sender_id: int, requested_time: Optional[NanosecondTime]=None) -> None:
        """
        Called by an agent to receive a "wakeup call" from the kernel at some requested
        future time.

        NOTE: The agent is responsible for maintaining any required state; the kernel
        will not supply any parameters to the ``wakeup()`` call.

        Arguments:
            sender_id: The ID of the agent making the call.
            requested_time: Defaults to the next possible timestamp.  Wakeup time cannot
            be the current time or a past time.
        """
        if requested_time is None:
            requested_time = self.current_time + 1
        if self.current_time and requested_time < self.current_time:
            raise ValueError('set_wakeup() called with requested time not in future', 'current_time:', self.current_time, 'requested_time:', requested_time)
        if self.show_trace_messages:
            if logger.isEnabledFor(10):
                logger.debug('Kernel adding wakeup for agent {} at time {}'.format(sender_id, fmt_ts(requested_time)))
        self.messages.put((requested_time, (sender_id, sender_id, WakeupMsg())))

    def get_agent_compute_delay(self, sender_id: int) -> int:
        """
        Allows an agent to query its current computation delay.

        Arguments:
            sender_id: The ID of the agent to get the computational delay for.
        """
        return self.agent_computation_delays[sender_id]

    def set_agent_compute_delay(self, sender_id: int, requested_delay: int) -> None:
        """
        Called by an agent to update its computation delay.

        This does not initiate a global delay, nor an immediate delay for the agent.
        Rather it sets the new default delay for the calling agent. The delay will be
        applied upon every return from wakeup or recvMsg. Note that this delay IS
        applied to any messages sent by the agent during the current wake cycle
        (simulating the messages popping out at the end of its "thinking" time).

        Also note that we DO permit a computation delay of zero, but this should really
        only be used for special or massively parallel agents.

        Arguments:
            sender_id: The ID of the agent making the call.
            requested_delay: delay given in nanoseconds.
        """
        if not isinstance(requested_delay, int):
            raise ValueError('Requested computation delay must be whole nanoseconds.', 'requested_delay:', requested_delay)
        if requested_delay < 0:
            raise ValueError('Requested computation delay must be non-negative nanoseconds.', 'requested_delay:', requested_delay)
        self.agent_computation_delays[sender_id] = requested_delay

    def delay_agent(self, sender_id: int, additional_delay: int) -> None:
        """
        Called by an agent to accumulate temporary delay for the current wake cycle.

        This will apply the total delay (at time of send_message) to each message, and
        will modify the agent's next available time slot.  These happen on top of the
        agent's compute delay BUT DO NOT ALTER IT. (i.e. effects are transient). Mostly
        useful for staggering outbound messages.

        Arguments:
            sender_id: The ID of the agent making the call.
            additional_delay: additional delay given in nanoseconds.
        """
        if not isinstance(additional_delay, int):
            raise ValueError('Additional delay must be whole nanoseconds.', 'additional_delay:', additional_delay)
        if additional_delay < 0:
            raise ValueError('Additional delay must be non-negative nanoseconds.', 'additional_delay:', additional_delay)
        self.current_agent_additional_delay += additional_delay

    def find_agents_by_type(self, agent_type: Type[Agent]) -> List[int]:
        """
        Returns the IDs of any agents that are of the given type.

        Arguments:
            type: The agent type to search for.

        Returns:
            A list of agent IDs that are instances of the type.
        """
        return [agent.id for agent in self.agents if isinstance(agent, agent_type)]

    def write_log(self, sender_id: int, df_log: pd.DataFrame, filename: Optional[str]=None) -> None:
        """
        Called by any agent, usually at the very end of the simulation just before
        kernel shutdown, to write to disk any log dataframe it has been accumulating
        during simulation.

        The format can be decided by the agent, although changes will require a special
        tool to read and parse the logs.  The Kernel places the log in a unique
        directory per run, with one filename per agent, also decided by the Kernel using
        agent type, id, etc.

        If there are too many agents, placing all these files in a directory might be
        unfortunate. Also if there are too many agents, or if the logs are too large,
        memory could become an issue. In this case, we might have to take a speed hit to
        write logs incrementally.

        If filename is not None, it will be used as the filename. Otherwise, the Kernel
        will construct a filename based on the name of the Agent requesting log archival.

        Arguments:
            sender_id: The ID of the agent making the call.
            df_log: dataframe representation of the log that contains all the events logged during the simulation.
            filename: Location on disk to write the log to.
        """
        if self.skip_log:
            return
        path = os.path.join('.', 'log', self.log_dir)
        if filename:
            file = '{}.bz2'.format(filename)
        else:
            file = '{}.bz2'.format(self.agents[sender_id].name.replace(' ', ''))
        if not os.path.exists(path):
            os.makedirs(path)
        df_log.to_pickle(os.path.join(path, file), compression='bz2')

    def append_summary_log(self, sender_id: int, event_type: str, event: Any) -> None:
        """
        We don't even include a timestamp, because this log is for one-time-only summary
        reporting, like starting cash, or ending cash.

        Arguments:
            sender_id: The ID of the agent making the call.
            event_type: The type of the event.
            event: The event to append to the log.
        """
        self.summary_log.append({'AgentID': sender_id, 'AgentStrategy': self.agents[sender_id].type, 'EventType': event_type, 'Event': event})

    def write_summary_log(self) -> None:
        path = os.path.join('.', 'log', self.log_dir)
        file = 'summary_log.bz2'
        if not os.path.exists(path):
            os.makedirs(path)
        df_log = pd.DataFrame(self.summary_log)
        df_log.to_pickle(os.path.join(path, file), compression='bz2')

    def update_agent_state(self, agent_id: int, state: Any) -> None:
        """
        Called by an agent that wishes to replace its custom state in the dictionary the
        Kernel will return at the end of simulation. Shared state must be set directly,
        and agents should coordinate that non-destructively.

        Note that it is never necessary to use this kernel state dictionary for an agent
        to remember information about itself, only to report it back to the config file.

        Arguments:
            agent_id: The agent to update state for.
            state: The new state.
        """
        if 'agent_state' not in self.custom_state:
            self.custom_state['agent_state'] = {}
        self.custom_state['agent_state'][agent_id] = state
