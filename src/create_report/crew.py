from crewai import Agent, Task, Crew, Process
from crewai_tools import SerperDevTool
from .tools.custom_tool import get_all_tools
import yaml
import os
from pathlib import Path
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class CrewOutput:
    def __init__(self, content: str):
        self.content = content
    
    def __str__(self):
        return self.content

class CrewManager:
    def __init__(self, config_path: Optional[str] = None, api_key: Optional[str] = None):
        self.api_key = api_key
        self.config_path = config_path or self._get_default_config_path()
        self.agents_config = self._load_config('agents.yaml')
        self.tasks_config = self._load_config('tasks.yaml')
        self.tools = self._setup_tools()
        self.agents = {}
        self.tasks = {}
        
    def _get_default_config_path(self) -> str:
        return os.path.join(os.path.dirname(__file__), 'config')
    
    def _load_config(self, filename: str) -> Dict[str, Any]:
        try:
            config_file = os.path.join(self.config_path, filename)
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Could not load {filename}: {str(e)}")
            return {}
    
    def _setup_tools(self) -> Dict[str, Any]:
        tools = {}
        try:
            for tool in get_all_tools(api_key=self.api_key):
                tools[tool.name] = tool
        except Exception as e:
            logger.warning(f"Could not load custom tools: {str(e)}")
        try:
            tools['search_tool'] = SerperDevTool()
        except Exception as e:
            logger.warning(f"Could not initialize SerperDevTool: {str(e)}")
        
        return tools
    
    def create_agent(self, agent_name: str, **kwargs) -> Agent:
        if agent_name not in self.agents_config:
            raise ValueError(f"Agent '{agent_name}' not found in configuration")
        
        config = self.agents_config[agent_name].copy()
        config.update(kwargs)
        agent_tools = []
        if 'tools' in config:
            for tool_name in config['tools']:
                if tool_name in self.tools:
                    agent_tools.append(self.tools[tool_name])
                else:
                    logger.warning(f"Tool '{tool_name}' not found for agent '{agent_name}'")

        agent = Agent(
            role=config.get('role', ''),
            goal=config.get('goal', ''),
            backstory=config.get('backstory', ''),
            tools=agent_tools,
            verbose=config.get('verbose', False),
            allow_delegation=config.get('allow_delegation', False)
        )
        
        self.agents[agent_name] = agent
        return agent
    
    def create_task(self, task_name: str, agents: Dict[str, Agent], **kwargs) -> Task:
        if task_name not in self.tasks_config:
            raise ValueError(f"Task '{task_name}' not found in configuration")
        
        config = self.tasks_config[task_name].copy()
        config.update(kwargs)
        
        agent_name = config.get('agent', '')
        if agent_name not in agents:
            raise ValueError(f"Agent '{agent_name}' not found for task '{task_name}'")
        
        task_dependencies = []
        if 'dependencies' in config:
            for dep_name in config['dependencies']:
                if dep_name in self.tasks:
                    task_dependencies.append(self.tasks[dep_name])
                else:
                    logger.warning(f"Dependency '{dep_name}' not found for task '{task_name}'")
        task = Task(
            description=config.get('description', ''),
            expected_output=config.get('expected_output', ''),
            agent=agents[agent_name]
        )
        
        self.tasks[task_name] = task
        return task
    
    def create_crew(self, topic: str, report_config: Dict[str, Any]) -> Crew:
        agents = {}
        agent_names = ['researcher', 'analyst', 'writer', 'reviewer']
        
        for agent_name in agent_names:
            try:
                agents[agent_name] = self.create_agent(agent_name)
            except Exception as e:
                logger.error(f"Failed to create agent '{agent_name}': {str(e)}")
                # Create a basic fallback agent
                agents[agent_name] = self._create_fallback_agent(agent_name)
        
        tasks = []
        task_names = ['research_task', 'analysis_task', 'writing_task', 'review_task']
        
        for task_name in task_names:
            try:
                task_kwargs = self._format_task_config(task_name, topic, report_config)
                task = self.create_task(task_name, agents, **task_kwargs)
                tasks.append(task)
            except Exception as e:
                logger.error(f"Failed to create task '{task_name}': {str(e)}")
                fallback_task = self._create_fallback_task(task_name, agents, topic)
                tasks.append(fallback_task)
        
        crew = Crew(
            agents=list(agents.values()),
            tasks=tasks,
            verbose=True,
            process=Process.sequential,
            memory=True
        )
        
        return crew
    
    def _format_task_config(self, task_name: str, topic: str, config: Dict[str, Any]) -> Dict[str, Any]:
        task_config = {}
        
        if task_name in self.tasks_config:
            original_config = self.tasks_config[task_name]
            if 'description' in original_config:
                task_config['description'] = original_config['description'].format(
                    topic=topic,
                    report_type=config.get('report_type', 'Comprehensive Analysis'),
                    length=config.get('length', 5),
                    include_sources_instruction=self._get_sources_instruction(config),
                    include_charts_instruction=self._get_charts_instruction(config)
                )
            
            if 'expected_output' in original_config:
                task_config['expected_output'] = original_config['expected_output'].format(
                    report_type=config.get('report_type', 'Comprehensive Analysis'),
                    length=config.get('length', 5)
                )
        
        return task_config
    
    def _get_sources_instruction(self, config: Dict[str, Any]) -> str:
        if config.get('include_sources', False):
            return "Include proper citations and references to all sources used in the research."
        return ""
    
    def _get_charts_instruction(self, config: Dict[str, Any]) -> str:
        if config.get('include_charts', False):
            return "Include suggestions for data visualizations and charts where appropriate."
        return ""
    
    def _create_fallback_agent(self, agent_name: str) -> Agent:
        return Agent(
            role=f"AI Assistant",
            goal=f"Assist with {agent_name} tasks",
            backstory=f"You are an AI assistant specializing in {agent_name} tasks.",
            verbose=True,
            allow_delegation=False
        )
    
    def _create_fallback_task(self, task_name: str, agents: Dict[str, Agent], topic: str) -> Task:
        agent = list(agents.values())[0] 
        
        return Task(
            description=f"Work on {task_name} for the topic: {topic}",
            expected_output=f"Results for {task_name}",
            agent=agent
        )

class ReportCrew:
    def __init__(self, api_key: Optional[str] = None):
        self.crew_manager = CrewManager(api_key=api_key)
    
    def generate_report(self, topic: str, config: Dict[str, Any]) -> str:
        try:
            crew = self.crew_manager.create_crew(topic, config)
            result = crew.kickoff()
            
            return str(result)
            
        except Exception as e:
            logger.error(f"Error generating report: {str(e)}")
            return self._generate_fallback_report(topic, config)
    
    def _generate_fallback_report(self, topic: str, config: Dict[str, Any]) -> str:
        from datetime import datetime
        
        return f"""
# {config.get('report_type', 'Report')}: {topic}

**Generated on:** {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}

## Executive Summary

This report addresses the topic: "{topic}". Due to system limitations, this is a simplified version of the requested report.

## Introduction

The topic "{topic}" represents an important area that requires careful analysis and strategic consideration.

## Key Findings

1. **Current State Analysis**: The current situation regarding {topic} presents both opportunities and challenges.

2. **Key Challenges**: Several factors need to be addressed to make progress on this topic.

3. **Opportunities**: There are significant opportunities for improvement and innovation.

## Recommendations

1. **Short-term Actions**: Immediate steps that can be taken to address the topic.

2. **Long-term Strategy**: Strategic approach for sustainable progress.

3. **Implementation Plan**: Framework for executing the recommendations.

## Conclusion

The analysis of "{topic}" reveals the need for a comprehensive approach that addresses both immediate challenges and long-term strategic goals.

---

*Note: This is a simplified report. For detailed analysis with comprehensive research, please ensure all system dependencies are properly configured.*
        """