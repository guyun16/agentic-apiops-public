package com.apiops.web.project.converter;

import com.apiops.web.project.domain.Project;
import com.apiops.web.project.domain.AccessibleProject;
import com.apiops.web.project.domain.ProjectMember;
import com.apiops.web.project.vo.AccessibleProjectVO;
import com.apiops.web.project.vo.ProjectMemberVO;
import com.apiops.web.project.vo.ProjectVO;
import org.springframework.stereotype.Component;

@Component
public class ProjectConverter {

    public AccessibleProjectVO toVO(AccessibleProject source) {
        return new AccessibleProjectVO(
                source.projectId(),
                source.projectName(),
                source.projectRole()
        );
    }

    public ProjectVO toVO(Project source) {
        return new ProjectVO(
                source.id(),
                source.projectKey(),
                source.projectName(),
                source.ownerUserId(),
                source.status(),
                source.createdAt(),
                source.updatedAt()
        );
    }

    public ProjectMemberVO toVO(ProjectMember source) {
        return new ProjectMemberVO(
                source.projectId(),
                source.userId(),
                source.projectRole(),
                source.joinedAt()
        );
    }
}
