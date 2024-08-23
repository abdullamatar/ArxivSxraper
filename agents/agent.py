# STD LIB
import logging
import os
import re
import sys
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union
from uuid import uuid4

# autogen
from autogen import (Agent, AssistantAgent, ConversableAgent, GroupChatManager,
                     UserProxyAgent)
from autogen.agentchat.contrib.retrieve_user_proxy_agent import \
    RetrieveUserProxyAgent
from autogen.agentchat.contrib.vectordb.base import QueryResults
from autogen.agentchat.groupchat import GroupChat
from autogen.code_utils import extract_code

# A2A
# import agents.agent_conf as agent_conf
from agents.agent_conf import base_cfg, retrieve_conf
from lib.embeddings import get_db_connection, get_embedding_func

# from trulens_eval import Tru


# from utils.misc import write_file

# TrueLens
# from trulens_eval.tru_custom_app import instrument


logger = logging.getLogger("agents")

logging.getLogger("requests").propagate = False
logging.getLogger("urllib3").propagate = False

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(
    level=logging.INFO,
    filename=os.path.join(root_dir, "logs/agents_mod.log"),
    format="%(asctime)s: From module %(module)s:\n%(message)s",
)

# U N D E R  C O N S T R U C T I O N
# ◉_◉
# self.register_reply(Agent, RetrieveUserProxyAgent._generate_retrieve_user_reply, position=2)
# This agent by default must be triggered by another agent ^, from src

# TODO: Dynamic agent creation, urls as rag src, md, readmes, notebooks...

TERMINATION_MSG = (
    lambda x: len(re.findall(r"TERMINATE", str(x.get("content", ""))[-9:].upper())) > 0
)

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# TERMINATION_MSG = (
#     lambda x: isinstance(x, dict)
#     and "TERMINATE" == str(x.get("content", ""))[-9:].upper()
# )


class EmbeddingRetrieverAgent(RetrieveUserProxyAgent):
    """Custom retriever agent that uses an embeddings database to retrieve relevant docs."""

    def __init__(
        self,
        collection_name: str,
        name: str = "RetrieveChatAgent",
        human_input_mode: Optional[str] = "ALWAYS",
        is_termination_msg: Optional[Callable[[Dict[str, Any]], bool]] = None,
        retrieve_config: Optional[
            Dict[str, str]
        ] = None,  # config for the retrieve agent
        **kwargs,
    ):
        self.embedding_function = get_embedding_func()
        self.dbconn = get_db_connection(
            cname=collection_name,
            efunc=self.embedding_function,
        )
        self.n_results = 5
        # self.customized_prompt
        super().__init__(
            name=name,
            human_input_mode=human_input_mode,
            is_termination_msg=is_termination_msg,
            retrieve_config=retrieve_config,
            **kwargs,
        )

    def query_vector_db(
        self,
        # query_texts: List[str],
        search_string: str,
        n_results: int = 5,
        **kwargs,
    ) -> Dict[str, List[List[str]]]:
        # ef = get_embedding_func()
        # embed_response = self.embedding_function.embed_query(query_texts)
        # print(n_results)
        n_results = self.n_results
        relevant_docs = self.dbconn.similarity_search_with_relevance_scores(
            query=search_string,
            k=int(n_results),
        )

        # TODO: get actual doc ids
        sim_score = [relevant_docs[i][1] for i in range(len(relevant_docs))]
        return {
            "ids": [i for i in range(len(relevant_docs))],
            "documents": [doc[0].page_content for doc in relevant_docs],
            "metadata": [
                {**doc[0].metadata, "similarity_score": score}
                for doc, score in zip(relevant_docs, sim_score)
            ],
        }  # type: ignore

    def transform_results_to_query_results(self, results) -> QueryResults:
        # TODO: Do this in one pass through retrieval, above function...
        query_results = []
        documents = []
        for idx in range(len(results["ids"])):
            document = {
                "id": results["ids"][idx],
                "content": results["documents"][idx],
                "metadata": results["metadata"][idx],
            }
            distance = results["metadata"][idx]["similarity_score"]
            documents.append((document, distance))
        query_results.append(documents)
        return query_results

    def retrieve_docs(
        self, search_string: str, problem: str, n_results: int = 5, **kwargs
    ):
        """
        Args:
            problem: the problem to be solved.
            n_results: the number of results to be retrieved. Default is 20.
            search_string: only docs that contain an exact match of this string will be retrieved. Default is "".
        """
        results = self.transform_results_to_query_results(
            self.query_vector_db(
                # query_texts=[problem],
                n_results=n_results,
                search_string=search_string,
                # embedding_function=get_embedding_func(),
                # embedding_model="text-embedding-ada-002",
                **kwargs,
            )
        )

        self._search_string = search_string
        # TODO: The northern winds blow strong...
        self._results = results  # Why?: It is a class property; state repr i guess?
        # return results

    # This is taken directly from the RetrieveUserProxyAgent class from autogen and is used as a hacky workaround to abide by the token limit of the GPT-3 family of models, it is commented out when using gpt4+.

    # def _get_context(self, results: Dict[str, List[str] | List[List[str]]]):
    #     doc_contents = ""
    #     current_tokens = 0
    #     _doc_idx = self._doc_idx
    #     _tmp_retrieve_count = 0
    #     for idx, doc in enumerate(results["documents"][0][:5]):
    #         if idx <= _doc_idx:
    #             continue
    #         if results["ids"][0][idx] in self._doc_ids:
    #             continue
    #         _doc_tokens = self.custom_token_count_function(doc, self._model)
    #         if _doc_tokens > self._context_max_tokens:
    #             func_print = f"Skip doc_id {results['ids'][0][idx]} as it is too long to fit in the context."
    #             print((func_print))
    #             self._doc_idx = idx
    #             continue
    #         if current_tokens + _doc_tokens > self._context_max_tokens:
    #             break
    #         func_print = f"Adding doc_id {results['ids'][0][idx]} to context."
    #         print((func_print))
    #         current_tokens += _doc_tokens
    #         doc_contents += doc + "\n"
    #         self._doc_idx = idx
    #         self._doc_ids.append(results["ids"][0][idx])
    #         self._doc_contents.append(doc)
    #         _tmp_retrieve_count += 1
    #         if _tmp_retrieve_count >= self.n_results:
    #             break
    #     return doc_contents


class CodingAssistant(AssistantAgent):
    # https://github.com/microsoft/autogen/blob/main/notebook/agentchat_auto_feedback_from_code_execution.ipynb
    def __init__(
        self,
        name: str,
        human_input_mode: str | Literal["NEVER"],
        system_message: str | None = None,
        llm_config: Optional[Union[Dict, Literal[False]]] = None,
        is_termination_msg: Callable[[Dict], bool] | None = None,
        max_consecutive_auto_reply: int | None = None,
        code_execution_config: Dict | Literal[False] | None = False,
        description: str | None = None,
        **kwargs,
    ):
        super().__init__(
            name,
            llm_config=llm_config,
            human_input_mode=human_input_mode,  # type: ignore
            code_execution_config=code_execution_config,
            description=description,
            system_message=system_message,
            # description,
            **kwargs,
        )
        # self.register_reply(trigger=[Agent, None], reply_func=self.i)

    # see comment in GCManager subclass
    # @instrument
    # def generate_reply(
    #     self,
    #     messages: List[Dict[str, Any]] | None = None,
    #     sender: Agent | None = None,
    #     **kwargs: Any,
    # ) -> str | Dict | None:
    #     return super().generate_reply(messages, sender, **kwargs)

    def detect_and_execute_code(
        self,
        message,
        **kwargs,
    ) -> List[Dict] | None:
        # kwargs.pop("last_n_messages", None)
        execution_feedback = []
        # for message in messages:
        # print(f"Typeof message: {type(message)}")
        code_blocks = extract_code(message["content"])
        # NOTE: Gonna make it always true for science
        if code_blocks or 1:
            for _, code in code_blocks:
                # Third unpacked element is str for docker image
                # ? Can modify run_code as needed
                exit_code, logs, _ = self.run_code(
                    code=code,  # **self._code_execution_config #this arg causes an error but is present in their src code
                )

                execution_feedback.append(
                    {"code": code, "exit_code": exit_code, "logs": logs}
                )
                # write_file(os.path.join(root_dir, f"sandbox/code_{uuid4()}.py"), code)
        # logger.info(f"Execution feedback: {execution_feedback}")
        return execution_feedback

    # ! run_code called in execute_code_blocks which is called in generate_code_execution_reply
    # code is extracted in generate_*_reply
    # def run_code(self, code, **kwargs):
    #     logger.info(f"RUNNING CODE:\n{code}")
    #     filename = f"code_gen_{random.randint(0, 1000)}"
    #     with open(f"sandbox/{filename}.py", "a") as f:
    #         f.write(code)
    #     return super().run_code(code, **kwargs)


class GCManager(GroupChatManager):
    def __init__(
        self,
        groupchat: GroupChat,
        tid,
        name: str | None = "chat_manager",
        max_consecutive_auto_reply: int | None = sys.maxsize,
        human_input_mode: str | None = "NEVER",
        llm_config: Optional[Union[Dict, Literal[False]]] = None,
        system_message: str | List | None = "Group chat manager.",
        **kwargs,
    ):
        super().__init__(
            groupchat,
            name,
            max_consecutive_auto_reply,
            human_input_mode,
            system_message,
            llm_config=llm_config,
            **kwargs,
        )
        self.register_reply(
            trigger=Agent, reply_func=GCManager.run_chat, config=groupchat
        )

        self.tid = tid
        self.execution_feedback_list = []

    # trulens has this instrument decorator on generate completion methods and retrieval methods, they are added to each agents generate reply, however it seems to expect a str while in autogen the generate_reply methods return may return a dict or None :D...
    # @instrument
    # def generate_reply(
    #     self,
    #     messages: List[Dict[str, Any]] | None = None,
    #     sender: Agent | None = None,
    #     **kwargs: Any,
    # ) -> str | Dict | None:
    #     return super().generate_reply(messages, sender, **kwargs)

    def is_code_block(self, message: Union[Dict, str]) -> bool:
        if isinstance(message, dict) and message.get("content") is None:
            return False
        elif not message:
            return False

        if isinstance(message, dict):
            content = message.get("content", "")
        elif isinstance(message, str):
            content = message

        return bool(
            re.compile(
                r"```[ \t]*(\w+)?[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL
            ).search(content)
        )

    def run_chat(
        self,
        messages: Optional[List[Dict]] = None,
        sender: Optional[Agent] = None,
        config: Optional[GroupChat] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Run a group chat."""
        # Adapted from /autogen/agentchat/groupchat.py:GroupChatManager.run_chat

        if messages is None:
            messages = self._oai_messages[sender]
        message = messages[-1]
        speaker = sender
        groupchat = config

        if self.client_cache is not None:
            for a in groupchat.agents:
                a.previous_cache = a.client_cache
                a.client_cache = self.client_cache

        exe_feedback = None

        coding_llm = groupchat.agents[-1]
        assert isinstance(coding_llm, CodingAssistant)

        # :D الله أكبر! تعليق بالعربي!
        for i in range(groupchat.max_round):
            # Isolate the coding LLM
            # change to check by name

            with open(os.path.join(root_dir, "logs/final_convs.log"), "a") as f:
                f.write(f"Round {i}\n")
                f.write(f"{speaker.name}:\n")
                f.write(f"{message['content']}\n")

            groupchat.append(message, speaker)

            # broadcast the message to all agents except the speaker
            for agent in groupchat.agents:
                if agent != speaker:
                    self.send(message, agent, request_reply=False, silent=True)
            if i == groupchat.max_round - 1:
                # the last round
                break

            # print(f"last msg for coging: {coding_llm.last_message(self)}")
            try:
                # select the next speaker
                speaker = groupchat.select_speaker(speaker, self)

                ###########################  A2A  ###################################
                ###########################  A2A  ###################################
                ###########################  A2A  ###################################
                ###########################  A2A  ###################################

                # IF FALSE ಥ_ಥ #
                if False and isinstance(speaker, CodingAssistant):
                    # if code in msg then execute and generate reply
                    # ? message, or what???
                    # TODO: How to best attach logs and exitcode to message

                    reply = speaker.generate_reply(sender=self)
                    # exe_feedback = speaker.detect_and_execute_code(message)
                # elif speaker.name == "code_reviewer" and exe_feedback:
                #     # speaker.
                #     reply = speaker.generate_reply(
                #         [
                #             *messages[-3:],
                #             {
                #                 "role": "assistant",
                #                 "content": f"{exe_feedback}\nGenerate an evaluation score for the code that has been generated given the above status, give the score first and then whatever suggestion you deem fit and necessary. REPLY EXACTLY EVALUATION SCORE=<score> followed by your suggestion on a new line where <score> is a float between 0 and 1.",
                #             },
                #         ],
                #         sender=self,
                #     )
                #     score_pattern = re.compile(r"EVALUATION SCORE=(\d+\.\d+)")

                #     # print(f"Reply: {reply}")
                #     # print(f"typeof reply: {type(reply)}")
                #     try:
                #         evaluation_score = re.findall(
                #             score_pattern,
                #             reply if isinstance(reply, str) else reply["content"],
                #         )
                #     except Exception as e:
                #         evaluation_score = -1
                #     logger.info(f"Evaluation score: {evaluation_score}")

                ###########################  A2A  ###################################
                ###########################  A2A  ###################################
                ###########################  A2A  ###################################
                ###########################  A2A  ###################################
                # else:
                # Let whoever the speaker is reply
                reply = speaker.generate_reply(sender=self)

            except KeyboardInterrupt:
                if groupchat.admin_name in groupchat.agent_names:
                    # admin agent is one of the participants
                    speaker = groupchat.agent_by_name(groupchat.admin_name)
                    reply = speaker.generate_reply(sender=self)
                else:
                    raise

            if reply is None:
                break

            # The speaker sends the message without requesting a reply
            speaker.send(reply, self, request_reply=False)
            message = self.last_message(speaker)

            if self.is_code_block(message):
                exe_feedback = coding_llm.detect_and_execute_code(
                    message,
                )

                # dumb hack to make sure the code reviewer has the chance to get the exe_feedback and evaluate
                i = groupchat.max_round - 2 if i == (groupchat.max_round - 1) else i

                self.execution_feedback_list.extend(exe_feedback)
                # x = {}
                # x["execution_feedback"] = self.execution_feedback_list
                # x["tid"] = self.tid
                # with open("new_runs.jsonl", "a") as g:
                #     g.write(json.dumps(x) + "\n")

        if self.client_cache is not None:
            for a in groupchat.agents:
                a.client_cache = a.previous_cache
                a.previous_cache = None
        return True, None


# To modify the way to execute code blocks, single code block, or function call, override execute_code_blocks, run_code, and execute_function methods respectively. (https://microsoft.github.io/autogen/docs/reference/agentchat/user_proxy_agent)


"""
From: https://github.com/microsoft/autogen/blob/main/notebook/agentchat_groupchat_RAG.ipynb
Call RetrieveUserProxyAgent while init chat with another user proxy agent
Sometimes, there might be a need to use RetrieveUserProxyAgent in group chat without initializing the chat with it. In such scenarios, it becomes essential to create a function that wraps the RAG agents and allows them to be called from other agents. WHY?
"""

# TODO: https://microsoft.github.io/autogen/blog/2023/10/26/TeachableAgent
# rc: https://microsoft.github.io/autogen/blog/2023/10/18/RetrieveChat/


def marl(collection_name: str) -> List[ConversableAgent]:
    agent0 = UserProxyAgent(
        name="main_userproxy",
        human_input_mode="NEVER",
        # code_execution_config=True,
        system_message="Conduct everything in a step by step manner, you are initiating the conversations, you are great at what you do. Please use the retrieve_content function, the more information you have the better.",
        description="Your role is to coordinate the completion of tasks related to generating code based off of machine learning and AI research. You must be diligent and operate in a step by step manner, make use of all the agents at your disposal.",
        llm_config=base_cfg,
    )

    retriever = EmbeddingRetrieverAgent(
        name="retriever",
        human_input_mode="NEVER",
        system_message="Retrieve additional information to complete the given task. Create a detailed query so that the retrieval is impactful in terms of information gained.",
        description="A retrieval augmented agent whose role is to retrieve additional information when asked, you can access an embeddings database with information related to code and research papers.",
        # code_execution_config=False,
        collection_name=collection_name,
        llm_config=retrieve_conf,
        retrieve_config={
            **retrieve_conf,
            "task": "qa",
            "client": "psycopg2",
        },
    )

    agent2 = AssistantAgent(
        name="code_reviewer",
        description="An agent used to review code, given the current information retrieved and other information related to the main problem at hand. Review the code generated by the coding_agent to make sure it is executable and logically follows the ideas from the research and source code.",
        system_message="Review the generated code, add to it and modify it as needed. Also retrieve additional information from the retrieval agent, plan out what you want to do and why in a step by step manner.",
        llm_config=base_cfg,
        is_termination_msg=TERMINATION_MSG,
        # code_execution_config={
        #     # "work_dir": "./sandbox",
        #     "use_docker": "python:3-slim",
        #     # "use_docker": "pytorch/pytorch:2.4.0-cuda11.8-cudnn9-runtime",
        # },
    )

    agent3 = CodingAssistant(
        name="coding_agent",
        system_message="Your role is to generate and execute code based off of the information provided by the retrieval agent and the code reviewer agent. Make sure you generate code in a step by step manner, use the feedback provided to improve your code. Make NO ASSUMPTIONS about anything, do not assume a file or package exist, if you must make assumptions state what they are. ALWAYS generate your code in a single code block between backticks and DO NOT BREAK IT UP, any comments you want to make can be ADDED OUTSIDE the code block, which must contain only the EXECUTABLE, CONCISE code related to the task given the instructions.",
        description="A coding agent that is tasked with iteratively generating code based off of the information provided related to the task as well as information from the retrieval agent and the code reviewer agent.",
        code_execution_config={
            # "work_dir": "./sandbox",
            "use_docker": "python:3-slim",
            # "use_docker": "pytorch/pytorch:2.4.0-cuda11.8-cudnn9-runtime",
            # "last_n_messages": 5,
        },
        # code_execution_config=False,
        # function_map={
        #     "execute_and_save": execute_and_save,
        # },
        human_input_mode="NEVER",
        is_termination_msg=TERMINATION_MSG,
        llm_config=base_cfg,
    )
    return [agent0, retriever, agent2, agent3]


if __name__ == "__main__":
    exit(9000)
    # nest_asyncio.apply()
    # asyncio.run(main())
