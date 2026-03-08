import git
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class GitSafetyManager:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        if not self.repo_path.exists() or not (self.repo_path / ".git").exists():
            raise ValueError(f"Not a valid git repository: {self.repo_path}")
        self.repo = git.Repo(self.repo_path)

    def is_clean(self) -> bool:
        """檢查工作區是否乾淨"""
        return not self.repo.is_dirty(untracked_files=True)

    def stash_changes(self, message: str = "Aegis auto stash"):
        """暫存目前的變更"""
        if not self.is_clean():
            logger.info(f"[{self.repo_path.name}] Stashing uncommitted changes...")
            self.repo.git.stash('save', '-u', message)
            return True
        return False

    def rollback_hard(self):
        """強制回滾所有未提交的變更 (致命錯誤時使用)"""
        logger.warning(f"[{self.repo_path.name}] Executing HARD RESET to clear failed AI changes!")
        self.repo.git.reset('--hard')
        self.repo.git.clean('-fd')

    def create_feature_branch(self, branch_name: str):
        """為 AI 任務建立獨立分支"""
        logger.info(f"[{self.repo_path.name}] Creating branch: {branch_name}")
        current_branch = self.repo.active_branch.name
        self.repo.git.checkout('-b', branch_name)
        return current_branch

    def commit_changes(self, message: str):
        """提交 AI 的變更"""
        if self.is_clean():
            logger.info(f"[{self.repo_path.name}] No changes to commit.")
            return False
        
        self.repo.git.add('-A')
        self.repo.git.commit('-m', message)
        logger.info(f"[{self.repo_path.name}] Committed: {message}")
        return True
