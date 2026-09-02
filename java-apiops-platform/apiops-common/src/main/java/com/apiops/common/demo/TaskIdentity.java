package com.apiops.common.demo;

import java.util.Objects;

public class TaskIdentity {
    private final String projectId;
    private final String taskId;

    public TaskIdentity(String projectId, String taskId) {
        this.projectId = projectId;
        this.taskId = taskId;
    }

    public String getTaskId() {
        return taskId;
    }

    public String getProjectId() {
        return projectId;
    }
    @Override
    public boolean equals(Object o){
        if(this == o){
            return true;
        }
        if(o == null || getClass() != o.getClass()){
            return false;
        }
        TaskIdentity that = (TaskIdentity) o;
        return Objects.equals(projectId, that.projectId) && Objects.equals(taskId, that.taskId);
    }
    @Override
    public int hashCode() {
        return Objects.hash(projectId, taskId);
    }

    @Override
    public String toString() {
        return "TaskIdentity{" +
                "projectId='" + projectId + '\'' +
                ", taskId='" + taskId + '\'' +
                '}';
    }
}