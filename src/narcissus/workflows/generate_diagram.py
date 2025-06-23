"""Generate workflow diagram"""
from llama_index.utils.workflow import draw_all_possible_flows

from narcissus.workflows.writer import WriterWorkflow

if __name__ == "__main__":
    draw_all_possible_flows(WriterWorkflow, filename="docs/workflow.html") 