package com.apiops.web.project.controller;

import com.apiops.common.result.Result;
import com.apiops.web.project.application.ProjectApplicationService;
import com.apiops.web.project.converter.ProjectConverter;
import com.apiops.web.project.vo.AccessibleProjectVO;
import com.apiops.web.project.dto.AddProjectMemberRequest;
import com.apiops.web.project.dto.CreateProjectRequest;
import com.apiops.web.project.dto.UpdateProjectRequest;
import com.apiops.web.project.vo.ProjectMemberVO;
import com.apiops.web.project.vo.ProjectVO;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/v1/projects")
public class ProjectController {

    private final ProjectApplicationService projectApplicationService;
    private final ProjectConverter projectConverter;

    public ProjectController(
            ProjectApplicationService projectApplicationService,
            ProjectConverter projectConverter
    ) {
        this.projectApplicationService = projectApplicationService;
        this.projectConverter = projectConverter;
    }

    @PostMapping
    public Result<ProjectVO> create(@RequestBody CreateProjectRequest request) {
        return Result.success(projectConverter.toVO(
                projectApplicationService.createProject(request)
        ));
    }

    @GetMapping
    public Result<List<AccessibleProjectVO>> list() {
        return Result.success(projectApplicationService.listAccessibleProjects().stream()
                .map(projectConverter::toVO)
                .toList());
    }

    @GetMapping("/{projectId}")
    public Result<ProjectVO> get(@PathVariable long projectId) {
        return Result.success(projectConverter.toVO(
                projectApplicationService.getProject(projectId)
        ));
    }

    @PutMapping("/{projectId}")
    public Result<ProjectVO> update(
            @PathVariable long projectId,
            @RequestBody UpdateProjectRequest request
    ) {
        return Result.success(projectConverter.toVO(
                projectApplicationService.updateProject(projectId, request)
        ));
    }

    @PostMapping("/{projectId}/members")
    public Result<ProjectMemberVO> addMember(
            @PathVariable long projectId,
            @RequestBody AddProjectMemberRequest request
    ) {
        return Result.success(projectConverter.toVO(
                projectApplicationService.addMember(projectId, request)
        ));
    }
}
