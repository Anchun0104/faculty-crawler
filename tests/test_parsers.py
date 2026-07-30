import unittest


from crawler.parsers import (
    FacultyRecord,
    _FacultyHTMLParser,
    _extract_name,
    _extract_title,
    _nearest_section_heading,
    _normalize_record_profile_url,
    find_linked_directory_sources,
    find_next_directory_page_url,
    parse_faculty_members,
    parse_faculty_page,
    remove_duplicates,
)


class ParserTests(unittest.TestCase):
    def test_linked_directory_discovery_stays_within_the_current_department(self) -> None:
        html = """
        <main>
          <a href="/en/departments/physics-and-astronomy/research/quantum/staff/">
            Quantum Physics staff
          </a>
          <a href="/en/departments/env/research/physical-resource-theory/staff/">
            Physical Resource Theory staff
          </a>
        </main>
        """

        result = find_linked_directory_sources(
            html,
            "https://www.example.edu/en/departments/physics-and-astronomy/research/",
            "example.edu",
        )

        self.assertEqual(
            result,
            [(
                "https://www.example.edu/en/departments/physics-and-astronomy/research/quantum/staff/",
                "faculty_directory",
            )],
        )

    def test_discovers_only_labelled_official_secondary_directories_and_portal(self) -> None:
        html = """
        <main>
          <a href="/physics/team">Team</a>
          <a href="/physics/mitarbeiter/mitarbeiterseiten">Mitarbeiterseiten</a>
          <a href="/physics/people/technical">Technical staff</a>
          <a href="/physics/news">People in the news</a>
          <a href="https://research.example.edu/portal/overview">Institutional Research Portal</a>
          <a href="/physics/institute/optics">Optics Research Group</a>
          <a href="/physics/research/quantum-lab">Quantum Physics Laboratory</a>
          <a href="https://outside.test/research-portal">Research portal</a>
          <a href="/physics/people/ada">Ada Lovelace</a>
        </main>
        """

        result = find_linked_directory_sources(
            html,
            "https://www.example.edu/physics/people",
            "example.edu",
        )

        self.assertEqual(
            result,
            [
                ("https://www.example.edu/physics/team", "faculty_directory"),
                ("https://www.example.edu/physics/mitarbeiter/mitarbeiterseiten", "faculty_directory"),
                ("https://research.example.edu/portal/overview", "research_portal"),
                ("https://www.example.edu/physics/institute/optics", "research_unit"),
                ("https://www.example.edu/physics/research/quantum-lab", "research_unit"),
            ],
        )

    def test_reliable_person_card_keeps_unknown_non_english_title_for_later_classification(self):
        html = """
        <main>
          <h2>Academic Staff</h2>
          <article class="person-card">
            <h3><a href="/people/cora-jones">Cora Jones</a></h3>
            <p>职位未知</p>
          </article>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/directory")

        self.assertEqual(
            [(record.name, record.title, record.profile_url) for record in result.records],
            [("Cora Jones", "职位未知", "https://example.edu/people/cora-jones")],
        )

    def test_extracts_faculty_cards_and_resolves_relative_urls(self):
        html = """
        <html>
          <body>
            <main>
              <article class="person-card">
                <h2><a href="/people/ada-lovelace/">Ada Lovelace</a></h2>
                <p>Professor of Electrical Engineering and Computer Science</p>
              </article>
              <article class="person-card">
                <h2><a href="https://example.edu/people/grace-hopper/">Grace Hopper</a></h2>
                <p>Associate Professor</p>
              </article>
            </main>
          </body>
        </html>
        """

        records = parse_faculty_members(html, "https://example.edu/faculty/")

        self.assertEqual([record.name for record in records], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(records[0].title, "Professor of Electrical Engineering and Computer Science")
        self.assertEqual(records[0].profile_url, "https://example.edu/people/ada-lovelace/")
        self.assertEqual(records[1].title, "Associate Professor")
        self.assertEqual(records[1].profile_url, "https://example.edu/people/grace-hopper/")

    def test_removes_duplicate_faculty_by_profile_url(self):
        html = """
        <section>
          <div class="faculty">
            <a href="/people/alan-turing/">Alan Turing</a>
            <span>Professor</span>
          </div>
          <div class="faculty">
            <a href="/people/alan-turing/">Alan Turing</a>
            <span>Professor of Mathematics</span>
          </div>
        </section>
        """

        records = parse_faculty_members(html, "https://example.edu/directory/")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].name, "Alan Turing")
        self.assertEqual(records[0].profile_url, "https://example.edu/people/alan-turing/")

    def test_keeps_named_record_when_title_is_missing(self):
        html = """
        <div class="people-list">
          <div class="person">
            <h3><a href="/profiles/katherine-johnson">Katherine Johnson</a></h3>
          </div>
        </div>
        """

        records = parse_faculty_members(html, "https://example.edu/faculty/")

        self.assertEqual(records, [])

    def test_ignores_navigation_and_footer_links(self):
        html = """
        <html>
          <body>
            <nav>
              <a href="/about">About</a>
              <a href="/contact">Contact</a>
            </nav>
            <main>
              <div class="profile-card">
                <a href="/people/barbara-liskov/">Barbara Liskov</a>
                <p>Institute Professor</p>
              </div>
            </main>
            <footer>
              <a href="/privacy">Privacy Policy</a>
            </footer>
          </body>
        </html>
        """

        records = parse_faculty_members(html, "https://example.edu/faculty/")

        self.assertEqual([record.name for record in records], ["Barbara Liskov"])

    def test_extracts_only_repeated_faculty_containers_from_directory_content(self):
        html = """
        <html>
          <body>
            <header>
              <a href="/people/faculty">Faculty</a>
              <a href="/research">Research</a>
            </header>
            <aside class="search">
              <label>Search</label>
              <a href="/people">People Directory</a>
            </aside>
            <main>
              <section class="people-grid">
                <div class="views-row faculty-card">
                  <img alt="Image: Sonya Atalay" src="/images/sonya.jpg">
                  <h3><a href="/people/sonya-atalay">Sonya Atalay</a></h3>
                  <p>Professor of Anthropology</p>
                  <p>E53-335F</p>
                  <p>sonya47@mit.edu</p>
                </div>
                <div class="views-row faculty-card">
                  <img alt="Image: Hector Beltran" src="/images/hector.jpg">
                  <h3><a href="/people/hector-beltran">Hector Beltran</a></h3>
                  <p>Class of 1957 Career Development Associate Professor</p>
                  <p>SHASS Faculty Fellow</p>
                  <p>hectorb@mit.edu</p>
                  <a href="https://hectorbeltran.org">Personal Website</a>
                </div>
              </section>
              <section>
                <h2>General Department Information</h2>
                <p>MIT Anthropology studies culture, technology, and society.</p>
              </section>
            </main>
            <footer>
              <a href="/faq">FAQ</a>
              <a href="/give">Give</a>
              <p>anthro@mit.edu</p>
            </footer>
          </body>
        </html>
        """

        records = parse_faculty_members(html, "https://anthropology.mit.edu/people/faculty")

        self.assertEqual([record.name for record in records], ["Sonya Atalay", "Hector Beltran"])
        self.assertEqual(records[0].title, "Professor of Anthropology")
        self.assertEqual(records[0].profile_url, "https://anthropology.mit.edu/people/sonya-atalay")
        self.assertEqual(records[1].title, "Class of 1957 Career Development Associate Professor")
        self.assertEqual(records[1].profile_url, "https://anthropology.mit.edu/people/hector-beltran")

    def test_rejects_faculty_container_when_profile_link_is_missing(self):
        html = """
        <main>
          <ul class="faculty-list">
            <li class="faculty-list__item">
              <h3>Jean Jackson</h3>
              <p>Professor of Anthropology (Emerita)</p>
              <p>jjackson@mit.edu</p>
            </li>
          </ul>
        </main>
        """

        records = parse_faculty_members(html, "https://anthropology.mit.edu/people/faculty")

        self.assertEqual(records, [])

    def test_discards_person_link_without_academic_title(self):
        html = """
        <main>
          <section class="people-grid">
            <div class="person-card">
              <h3><a href="/people/jane-example">Jane Example</a></h3>
              <p>Read more about our department community.</p>
            </div>
          </section>
        </main>
        """

        records = parse_faculty_members(html, "https://example.edu/people/faculty")

        self.assertEqual(records, [])

    def test_extracts_table_rows_without_cross_row_field_bleed(self):
        html = """
        <main>
          <table id="table-directory">
            <thead>
              <tr>
                <th>Name</th>
                <th>Title</th>
                <th>Email</th>
                <th>Phone</th>
              </tr>
            </thead>
            <tbody>
              <tr class="html">
                <td>
                  <span class="anchor"><span id="A"></span></span>
                  <a href="https://agsci.psu.edu/directory/tma13">Tim Abbey</a>
                </td>
                <td>Extension Educator, Horticulture - Green Industry</td>
                <td><a href="mailto:tma13@psu.edu">tma13@psu.edu</a></td>
                <td><a href="tel:717-840-7408">717-840-7408</a></td>
              </tr>
              <tr class="html">
                <td><a href="https://agsci.psu.edu/directory/aic">Charles Abdalla, Ph.D.</a></td>
                <td>Professor Emeritus, Agricultural and Environmental Economics</td>
                <td><a href="mailto:cabdalla@psu.edu">cabdalla@psu.edu</a></td>
                <td></td>
              </tr>
            </tbody>
          </table>
        </main>
        """

        result = parse_faculty_page(html, "https://agsci.psu.edu/directory")

        self.assertEqual(result.page_type, "table")
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.failure_stage, "low_coverage_warning")
        self.assertEqual([record.name for record in result.records], ["Tim Abbey", "Charles Abdalla"])
        self.assertEqual(result.records[0].title, "Extension Educator, Horticulture - Green Industry")
        self.assertEqual(result.records[0].profile_url, "https://agsci.psu.edu/directory/tma13")
        self.assertEqual(result.records[1].title, "Professor Emeritus, Agricultural and Environmental Economics")
        self.assertEqual(result.records[1].profile_url, "https://agsci.psu.edu/directory/aic")

    def test_accepts_slug_profile_links_inside_valid_faculty_cards(self):
        html = """
        <main>
          <div class="layout__region layout__region--second">
            <nav role="navigation" aria-labelledby="-menu" class="block block-menu-block block-menu-blockmain">
              <h2 id="-menu">Main navigation</h2>
              <ul class="subnav">
                <li><a href="/faculty">Faculty</a></li>
                <li><a href="/lbj-faculty-experts-guide">Faculty Experts Guide</a></li>
                <li><a href="/research-centers">Centers</a></li>
              </ul>
            </nav>
          </div>
          <div class="faculty-view">
            <div class="views-col col-1">
              <div class="views-field views-field-nothing">
                <span class="field-content">
                  <div class="faculty-caption">
                    <a href="/abner-gordon"><img alt="LBJ School Associate Professor Gordon Abner"></a>
                    <h4><a href="/abner-gordon">Gordon Abner</a></h4>
                    <span><em>Associate Professor</em></span>
                  </div>
                </span>
              </div>
            </div>
            <div class="views-col col-2">
              <div class="faculty-caption">
                <a href="/aiken-abigail-ra"><img alt="Abigail Aiken, assistant professor of public affairs"></a>
                <h4><a href="/aiken-abigail-ra">Abigail R.A. Aiken</a></h4>
                <span><em>Professor</em></span>
              </div>
            </div>
          </div>
        </main>
        """

        records = parse_faculty_members(html, "https://lbj.utexas.edu/faculty")

        self.assertEqual([record.name for record in records], ["Gordon Abner", "Abigail R.A. Aiken"])
        self.assertEqual(records[0].profile_url, "https://lbj.utexas.edu/abner-gordon")
        self.assertEqual(records[1].profile_url, "https://lbj.utexas.edu/aiken-abigail-ra")

    def test_extracts_oxford_engineering_compact_name_list_items(self):
        html = """
        <main>
          <div class="namelist">
            <ul class="namelist-list">
              <li class="namelist-name">
                <a href="/people/sinan-acikgoz">Acikgoz ,&nbsp;Sinan<span> Professor</span>
                  <div class="job-role">Associate Professor of Engineering Science</div>
                </a>
              </li>
              <li class="namelist-name">
                <a href="/people/mihai-badiu">Badiu,&nbsp;Mihai<span> Dr</span>
                  <div class="job-role">Departmental Lecturer</div>
                </a>
              </li>
            </ul>
          </div>
        </main>
        """

        records = parse_faculty_members(html, "https://eng.ox.ac.uk/people?c=ac")

        self.assertEqual([record.name for record in records], ["Acikgoz, Sinan", "Badiu, Mihai"])
        self.assertEqual(records[0].title, "Associate Professor of Engineering Science")
        self.assertEqual(records[0].profile_url, "https://eng.ox.ac.uk/people/sinan-acikgoz")
        self.assertEqual(records[1].title, "Departmental Lecturer")
        self.assertEqual(records[1].profile_url, "https://eng.ox.ac.uk/people/mihai-badiu")

    def test_extracts_eth_zurich_person_detail_cards(self):
        html = """
        <main>
          <div class="text-image cq-dd-image">
            <figure><img alt="Paolo Arosio"></figure>
            <p><a href="/en/the-department/people/faculty/person-detail.parosio.html" class="eth-link">Prof. Dr. Paolo Arosio</a><br>
              <b> Head of Institute ICB<br></b>
              ICB | Biochemical Engineering<br>
              <a href="https://arosiogroup.ethz.ch/" class="eth-link">Group Website</a></p>
          </div>
          <div class="text-image cq-dd-image">
            <figure><img alt="Prof. Dr. Sarbajit Banerjee"></figure>
            <p><a href="/en/the-department/people/faculty/person-detail.sbanerjee.html" class="eth-link">Prof. Dr. Sarbajit Banerjee</a><br>
              LAC | Battery Materials<br>
              <a href="https://example.com/group" class="eth-link">Group Website</a></p>
          </div>
          <div class="text-image cq-dd-image">
            <h2>Titulary Professors and Professors of Practice</h2>
            <p>Research groups that are not associated with a professorship can be found here:</p>
          </div>
        </main>
        """

        records = parse_faculty_members(html, "https://chab.ethz.ch/en/the-department/people/faculty.html")

        self.assertEqual([record.name for record in records], ["Prof. Dr. Paolo Arosio", "Prof. Dr. Sarbajit Banerjee"])
        self.assertEqual(records[0].title, "ICB | Biochemical Engineering")
        self.assertEqual(
            records[0].profile_url,
            "https://chab.ethz.ch/en/the-department/people/faculty/person-detail.parosio.html",
        )
        self.assertEqual(records[1].title, "LAC | Battery Materials")
        self.assertEqual(
            records[1].profile_url,
            "https://chab.ethz.ch/en/the-department/people/faculty/person-detail.sbanerjee.html",
        )

    def test_fallback_extracts_compact_staff_profile_links(self):
        html = """
        <html>
          <body>
            <header>
              <a href="https://www.law.hku.hk/academic-staff/">Academic Staff</a>
            </header>
            <main>
              <div class="staff filter-entry">
                <a href="https://www.law.hku.hk/academic_staff/vivian-cm-chan/">
                  <h2><span>Vivian CM</span> <span>Chan</span></h2>
                  <p id="profession">Senior Lecturer</p>
                </a>
              </div>
              <div class="staff filter-entry">
                <a href="https://www.law.hku.hk/academic_staff/dr-jiapei-tao/">
                  <h2><span>Dr Jiapei</span> <span>Tao</span></h2>
                  <p id="profession">Post-Doctoral Fellow</p>
                </a>
              </div>
              <p><a href="/academic_staff/james-si-zeng/">Prof. James Si Zeng Associate Professor</a></p>
              <p><a href="/academic-staff/">Category: Academic Staff</a></p>
            </main>
            <footer>
              <a href="https://www.law.hku.hk/academic_staff/footer-link/">Footer Person</a>
            </footer>
          </body>
        </html>
        """

        records = parse_faculty_members(html, "https://www.law.hku.hk/academic-staff/")

        self.assertEqual([record.name for record in records], ["Vivian CM Chan", "Dr Jiapei Tao", "Prof. James Si Zeng"])
        self.assertEqual([record.title for record in records], ["Senior Lecturer", "Post-Doctoral Fellow", "Associate Professor"])
        self.assertEqual(records[2].profile_url, "https://www.law.hku.hk/academic_staff/james-si-zeng/")

    def test_fallback_extracts_epfl_member_cards_with_lab_titles(self):
        html = """
        <main>
          <div class="members-listing">
            <div class="member-details">
              <a class="people-link-title" href="https://people.epfl.ch/349143">
                <div class="member-title">
                  <span class="member-lastname">Abitbol</span>
                  <span class="member-firstname">Tiffany</span>
                </div>
              </a>
              <a class="lab-website-link" href="https://www.epfl.ch/labs/sml/">
                <span>Sustainable Materials Laboratory</span>
              </a>
            </div>
            <div class="member-details">
              <a class="people-link-title" href="https://people.epfl.ch/175309">
                <div class="member-title">
                  <span class="member-lastname">Achouri</span>
                  <span class="member-firstname">Karim</span>
                </div>
              </a>
              <a class="lab-website-link" href="https://www.epfl.ch/labs/leap/">
                <span>Laboratory for Advanced Electromagnetics and Photonics</span>
              </a>
            </div>
          </div>
        </main>
        """

        records = parse_faculty_members(html, "https://sti.epfl.ch/faculty-members/")

        self.assertEqual([record.name for record in records], ["Abitbol Tiffany", "Achouri Karim"])
        self.assertEqual(records[0].title, "Sustainable Materials Laboratory")
        self.assertEqual(records[0].profile_url, "https://people.epfl.ch/349143")
        self.assertEqual(records[1].title, "Laboratory for Advanced Electromagnetics and Photonics")

    def test_fallback_extracts_mcgill_full_time_faculty_list_items(self):
        html = """
        <main>
          <h2><a name="FAC"></a>Full-time faculty members</h2>
          <ul>
            <li><a href="https://www.mcgill.ca/law/about/profs/anker-kirsten"><b>Kirsten Anker</b></a><br>
              Associate Professor<br>
              Tel.: <a href="tel:514-398-8147">514-398-8147</a>
            </li>
            <li><a href="https://www.mcgill.ca/law/about/profs/bjorklund-andrea"><b>Andrea Bjorklund</b></a><br>
              Full Professor<br>
            </li>
          </ul>
          <h2><a name="MEMBERS"></a>Members</h2>
          <ul>
            <li><a href="https://www.mcgill.ca/anthropology/people/ronaldniezen"><strong>Ron Niezen</strong></a>, Associate Member</li>
          </ul>
        </main>
        """

        records = parse_faculty_members(html, "https://www.mcgill.ca/law/profs#FAC")

        self.assertEqual([record.name for record in records], ["Kirsten Anker", "Andrea Bjorklund"])
        self.assertEqual([record.title for record in records], ["Associate Professor", "Full Professor"])
        self.assertEqual(records[0].profile_url, "https://www.mcgill.ca/law/about/profs/anker-kirsten")

    def test_extracts_cuhk_research_interest_grouped_staff_records_once(self):
        html = """
        <main>
          <h4><a href="/app/people/research-interest/">&lt; Back</a></h4>
          <div class="elementor-accordion-title">Comparative Law</div>
          <div class="staff_rec row">
            <div class="staff_name"><a href="https://www.law.cuhk.edu.hk/app/people/prof-anatole-boute">Prof. Anatole BOUTE</a></div>
            <div class="staff_title"><a href="https://www.law.cuhk.edu.hk/app/people/prof-anatole-boute">Professor</a></div>
          </div>
          <div class="staff_rec row">
            <div class="staff_name"><a href="https://www.law.cuhk.edu.hk/app/people/prof-asif-hameed/">Prof. Asif HAMEED</a></div>
            <div class="staff_title"><a href="https://www.law.cuhk.edu.hk/app/people/prof-asif-hameed/">Associate Professor</a></div>
          </div>
          <div class="elementor-accordion-title">European Law</div>
          <div class="staff_rec row">
            <div class="staff_name"><a href="https://www.law.cuhk.edu.hk/app/people/prof-anatole-boute">Prof. Anatole BOUTE</a></div>
            <div class="staff_title"><a href="https://www.law.cuhk.edu.hk/app/people/prof-anatole-boute">Professor</a></div>
          </div>
        </main>
        """

        records = parse_faculty_members(
            html,
            "https://www.law.cuhk.edu.hk/app/people/research-interest/international-comparative-law/",
        )

        self.assertEqual([record.name for record in records], ["Prof. Anatole BOUTE", "Prof. Asif HAMEED"])
        self.assertEqual([record.title for record in records], ["Professor", "Associate Professor"])
        self.assertEqual(records[0].profile_url, "https://www.law.cuhk.edu.hk/app/people/prof-anatole-boute")

    def test_extracts_edinburgh_people_table_rows(self):
        html = """
        <main>
          <nav><a href="/people/a">A</a><a href="/people/b">B</a></nav>
          <table class="table-people">
            <tbody>
              <tr>
                <td class="h3"><strong><a href="/people/ms-jane-cornwell"><span>Ms Jane Cornwell</span></a></strong></td>
                <td>Senior Lecturer in Intellectual Property Law</td>
                <td><a href="/people/ms-jane-cornwell">View profile</a></td>
              </tr>
              <tr>
                <td class="h3"><strong><a href="/people/dr-stephen-coutts"><span>Dr Stephen Coutts</span></a></strong></td>
                <td>Lecturer in EU Law</td>
                <td><a href="/people/dr-stephen-coutts">View profile</a></td>
              </tr>
            </tbody>
          </table>
        </main>
        """

        result = parse_faculty_page(html, "https://www.law.ed.ac.uk/people")

        self.assertEqual(result.candidate_count, 2)
        self.assertEqual([record.name for record in result.records], ["Ms Jane Cornwell", "Dr Stephen Coutts"])
        self.assertEqual([record.title for record in result.records], ["Senior Lecturer in Intellectual Property Law", "Lecturer in EU Law"])
        self.assertEqual(result.records[0].profile_url, "https://www.law.ed.ac.uk/people/ms-jane-cornwell")

    def test_reports_detection_failure_when_no_candidate_records_exist(self):
        html = """
        <main>
          <section>
            <h1>Department News</h1>
            <p>General page text without faculty records.</p>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/faculty")

        self.assertEqual(result.records, [])
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.parsed_count, 0)
        self.assertEqual(result.failure_stage, "detection")

    def test_large_directory_with_one_record_reports_low_coverage_warning(self):
        html = (
            "<html><head><title>Faculty Directory</title></head><body><main>"
            "<article class='person-card'><h2><a href='/people/ada-lovelace'>Ada Lovelace</a></h2>"
            "<p>Professor of Computing</p></article>"
            + ("<p>Faculty research and academic directory text.</p>" * 900)
            + "</main></body></html>"
        )

        result = parse_faculty_page(html, "https://example.edu/faculty")

        self.assertEqual(result.parsed_count, 1)
        self.assertEqual(result.failure_stage, "low_coverage_warning")

    def test_parent_container_with_many_profile_links_is_split(self):
        html = """
        <main>
          <section class="faculty-list">
            <div class="faculty-directory">
              <h2>Academic Faculty</h2>
              <p><a href="/people/ada-lovelace">Ada Lovelace</a> Professor</p>
              <p><a href="/people/grace-hopper">Grace Hopper</a> Associate Professor</p>
              <p><a href="/people/katherine-johnson">Katherine Johnson</a> Assistant Professor</p>
              <p><a href="/people/barbara-liskov">Barbara Liskov</a> Institute Professor</p>
              <p><a href="/people/frances-allen">Frances Allen</a> Professor Emerita</p>
            </div>
          </section>
        </main>
        """

        records = parse_faculty_members(html, "https://example.edu/faculty")

        self.assertEqual(
            [record.name for record in records],
            ["Ada Lovelace", "Grace Hopper", "Katherine Johnson", "Barbara Liskov", "Frances Allen"],
        )
        self.assertTrue(all(record.profile_url for record in records))

    def test_titled_person_links_in_listing_block_are_split(self):
        html = """
        <main>
          <section class="faculty-list">
            <div class="university-entity-page-tabs-inner">
              <span>All Faculty</span>
              <span>A - C</span>
              <span>46 Results were found</span>
            </div>
            <div class="university-entity-faces-display">
              <div class="uentity_marketing_preview_list">
                <a href="/profile/ronen3112_89">
                  <div class="tau-overlay-image-desc">Prof. Ronen Avraham</div>
                </a>
              </div>
              <div class="uentity_marketing_preview_list">
                <a href="/profile/ofrabloch">
                  <div class="tau-overlay-image-desc">Dr. Ofra Bloch</div>
                </a>
              </div>
            </div>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://en-law.tau.ac.il/full_time_faculty")

        self.assertEqual([record.name for record in result.records], ["Ronen Avraham", "Ofra Bloch"])
        self.assertEqual([record.title for record in result.records], ["Prof.", "Dr."])
        self.assertEqual(result.records[0].profile_url, "https://en-law.tau.ac.il/profile/ronen3112_89")
        self.assertNotIn("Prof.", result.records[0].name)
        self.assertTrue(
            all(debug["drop_reason"] != "multiple_profile_links" for debug in result.dropped_candidate_debug)
        )

    def test_same_path_person_query_profile_url_is_kept(self):
        base_url = "https://www.massey.ac.nz/massey/expertise/college-staff-lists/college-of-sciences/school-of-built-environment-staff/all-staff_home.cfm"
        for query in ("stref=489004", "staffId=489004", "staffid=489004", "personId=489004", "personid=489004", "profileId=489004", "profileid=489004", "id=489004"):
            with self.subTest(query=query):
                html = f"""
                <main>
                  <section class="staff-list">
                    <div class="faculty-card">
                      <h2><a href="all-staff_home.cfm?{query}">Dr Benjamin Ababio</a></h2>
                      <p>Lecturer in Built Environment</p>
                      <a href="mailto:B.Ababio@massey.ac.nz">B.Ababio@massey.ac.nz</a>
                    </div>
                  </section>
                </main>
                """

                result = parse_faculty_page(html, base_url)

                self.assertEqual(result.parsed_count, 1)
                self.assertEqual(result.records[0].name, "Dr Benjamin Ababio")
                self.assertEqual(result.records[0].title, "Lecturer in Built Environment")
                self.assertEqual(result.records[0].profile_url, f"{base_url}?{query}")
                self.assertNotIn(
                    "profile_url_is_page_url",
                    [debug["drop_reason"] for debug in result.dropped_candidate_debug],
                )

        html = """
        <main>
          <section class="staff-list">
            <div class="faculty-card">
              <h2><a href="all-staff_home.cfm?id=abc">Dr Benjamin Ababio</a></h2>
              <p>Lecturer in Built Environment</p>
            </div>
          </section>
        </main>
        """

        result = parse_faculty_page(html, base_url)

        self.assertEqual(result.parsed_count, 0)
        self.assertIn("profile_url_is_page_url", [debug["drop_reason"] for debug in result.dropped_candidate_debug])

    def test_profile_url_canonicalization_preserves_identity_and_drops_tracking(self):
        first = "https://example.edu/person/?member=AAA&utm_source=news&utm_medium=email&fbclid=one"
        duplicate = "https://example.edu/person/?gclid=two&utm_campaign=summer&member=AAA"
        second = "https://example.edu/person/?member=BBB"

        self.assertEqual(_normalize_record_profile_url(first), "https://example.edu/person?member=aaa")
        self.assertEqual(_normalize_record_profile_url(first), _normalize_record_profile_url(duplicate))
        self.assertNotEqual(_normalize_record_profile_url(first), _normalize_record_profile_url(second))
        self.assertEqual(
            _normalize_record_profile_url("https://example.edu/person/?page=2&department=psychology"),
            "https://example.edu/person",
        )
        self.assertEqual(
            _normalize_record_profile_url("https://example.edu/people/ada-lovelace"),
            "https://example.edu/people/ada-lovelace",
        )

        records = remove_duplicates(
            [
                FacultyRecord("Ada Adams", "Professor", first),
                FacultyRecord("Ada Adams", "Professor", duplicate),
                FacultyRecord("Bryn Baker", "Associate Professor", second),
            ]
        )
        self.assertEqual([record.name for record in records], ["Ada Adams", "Bryn Baker"])

    def test_keeps_query_identity_faculty_distinct_and_excludes_staff(self):
        html = """
        <main>
          <section>
            <h2>Faculty</h2>
            <article class="faculty-card">
              <a class="person-name" href="/person/?id=AAA">Ada Adams</a>
              <span class="person-title">Professor</span>
            </article>
            <article class="faculty-card">
              <a class="person-name" href="/person/?id=BBB">Bryn Baker</a>
              <span class="person-title">Associate Professor</span>
            </article>
            <article class="faculty-card">
              <a class="person-name" href="/person/?id=CCC&utm_source=directory">Cleo Carter</a>
              <span class="person-title">Assistant Professor</span>
            </article>
          </section>
          <section>
            <h2>Staff</h2>
            <article class="faculty-card">
              <a class="person-name" href="/person/?id=STAFF">Alex Admin</a>
              <span class="person-title">Program Coordinator</span>
            </article>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/psychology/people/")

        self.assertEqual(result.candidate_count, 3)
        self.assertEqual(result.possible_person_link_count, 4)
        self.assertEqual(result.parsed_count, 3)
        self.assertEqual([record.name for record in result.records], ["Ada Adams", "Bryn Baker", "Cleo Carter"])
        self.assertEqual(
            [record.profile_url for record in result.records],
            [
                "https://example.edu/person/?id=AAA",
                "https://example.edu/person/?id=BBB",
                "https://example.edu/person/?id=CCC&utm_source=directory",
            ],
        )
        self.assertNotIn("Alex Admin", [record.name for record in result.records])

    def test_person_endpoint_pagination_and_filter_queries_are_not_profiles(self):
        html = """
        <main>
          <div class="faculty-card">
            <a class="person-name" href="/person/?page=2">Paige Turner</a>
            <span class="person-title">Professor</span>
          </div>
          <div class="faculty-card">
            <a class="person-name" href="/person/?department=psychology">Fiona Fields</a>
            <span class="person-title">Associate Professor</span>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/psychology/people/")

        self.assertEqual(result.parsed_count, 0)
        self.assertTrue(
            all(item["drop_reason"] == "profile_url_is_page_url" for item in result.dropped_candidate_debug)
        )

    def test_heading_and_description_are_not_used_as_person_record(self):
        html = """
        <main>
          <section class="faculty-list">
            <div class="faculty-card">
              <h2>Academic Faculty</h2>
              <p>Our professors work across many research areas.</p>
              <a href="/people/ada-lovelace">Ada Lovelace</a>
              <p>Professor of Computing</p>
            </div>
          </section>
        </main>
        """

        records = parse_faculty_members(html, "https://example.edu/faculty")

        self.assertEqual([record.name for record in records], ["Ada Lovelace"])

    def test_fallback_replaces_sparse_standard_parse_when_it_finds_more_profiles(self):
        html = """
        <main>
          <section class="faculty-list faculty-card">
            <h2><a href="/people/ada-lovelace">Ada Lovelace</a></h2>
            <p>Professor of Computing</p>
            <p><a href="/people/grace-hopper">Grace Hopper</a> Associate Professor</p>
            <p><a href="/people/katherine-johnson">Katherine Johnson</a> Assistant Professor</p>
          </section>
        </main>
        """

        records = parse_faculty_members(html, "https://example.edu/faculty")

        self.assertEqual([record.name for record in records], ["Ada Lovelace", "Grace Hopper", "Katherine Johnson"])

    def test_fallback_does_not_create_records_without_profile_url(self):
        html = """
        <main>
          <section class="people-list">
            <p>Ada Lovelace Professor of Computing ada@example.edu</p>
            <p>Grace Hopper Associate Professor grace@example.edu</p>
          </section>
        </main>
        """

        records = parse_faculty_members(html, "https://example.edu/faculty")

        self.assertEqual(records, [])

    def test_detects_repeated_filterable_name_link_cards(self):
        html = """
        <html>
          <body>
            <div id="content">
              <div class="filterable">
                <a href="anderson-john.html"><img alt="John Anderson"></a>
                <h2><a class="name" href="anderson-john.html">John Anderson</a></h2>
                <h3>Richard King Mellon University Professor of Psychology and Computer Science</h3>
                <p><a class="cta" href="anderson-john.html">Read full bio</a></p>
              </div>
              <div class="filterable">
                <a href="bruder-jennifer.html"><img alt="Jennifer Bruder"></a>
                <h2><a class="name" href="bruder-jennifer.html">Jennifer Bruder</a></h2>
                <h3>Associate Teaching Professor, Psychology</h3>
                <p><a class="cta" href="bruder-jennifer.html">Read full bio</a></p>
              </div>
              <div class="filterable">
                <a href="cantlon-jessica.html"><img alt="Jessica Cantlon"></a>
                <h2><a class="name" href="cantlon-jessica.html">Jessica Cantlon</a></h2>
                <h3>Professor of Psychology</h3>
                <p><a class="cta" href="cantlon-jessica.html">Read full bio</a></p>
              </div>
              <div>
                <div class="nav-list">
                  <ul>
                    <li><a href="../../community-standards.html">Community Standards</a></li>
                    <li><a href="../../faculty-resources/index.html">Faculty Resources</a></li>
                  </ul>
                </div>
              </div>
            </div>
          </body>
        </html>
        """

        result = parse_faculty_page(html, "https://www.cmu.edu/dietrich/psychology/directory/core-training-faculty/index.html")

        self.assertEqual(result.candidate_count, 3)
        self.assertEqual([record.name for record in result.records], ["John Anderson", "Jennifer Bruder", "Jessica Cantlon"])
        self.assertEqual(result.records[0].profile_url, "https://www.cmu.edu/dietrich/psychology/directory/core-training-faculty/anderson-john.html")

    def test_link_list_profile_links_become_candidates_even_without_titles(self):
        html = """
        <html>
          <body>
            <main>
              <h1>All professors</h1>
              <ul class="professor-list">
                <li><h2>Ada Lovelace</h2><a href="/en/profile/ada-lovelace">view profile</a></li>
                <li><h2>Grace Hopper</h2><a href="/en/profile/grace-hopper">view profile</a></li>
              </ul>
            </main>
          </body>
        </html>
        """

        result = parse_faculty_page(html, "https://example.edu/professors/all-professors.html")

        self.assertEqual(result.possible_person_link_count, 2)
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.parsed_count, 0)
        self.assertEqual(result.failure_stage, "extraction")

    def test_detects_duke_law_faculty_profile_paths(self):
        html = """
        <html>
          <body>
            <main>
              <section class="faculty-profiles">
                <div class="faculty-card">
                  <h3><a href="/fac/abrams">Kerry Abrams</a></h3>
                  <p>Distinguished Professor of Law</p>
                </div>
                <div class="faculty-card">
                  <h3><a href="/fac/adler">Matthew Adler</a></h3>
                  <p>Richard A. Horvitz Distinguished Professor of Law</p>
                </div>
              </section>
            </main>
          </body>
        </html>
        """

        result = parse_faculty_page(html, "https://law.duke.edu/fac/")

        self.assertEqual(result.possible_person_link_count, 2)
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.parsed_count, 2)
        self.assertEqual(result.failure_stage, "none")
        self.assertEqual(result.records[0].profile_url, "https://law.duke.edu/fac/abrams")

    def test_extracts_single_cell_academic_leadership_rows(self):
        html = """
        <main>
          <div class="text js-responsive-tables">
            <table>
              <tbody>
                <tr><td><b>Acting Dean</b> - <a href="https://profiles.auckland.ac.nz/s-watson">Professor Susan Watson</a></td></tr>
                <tr><td><b>Acting Deputy Dean</b> - <a href="https://profiles.auckland.ac.nz/j-ip">Associate Professor John Ip</a></td></tr>
                <tr><td><b>Associate Dean (Academic)</b> - <a href="https://profiles.auckland.ac.nz/an-hertogen">Associate Professor An Hertogen</a></td></tr>
                <tr><td><b>Associate Dean (Curriculum, Teaching and Learning)</b> - <a href="https://profiles.auckland.ac.nz/bronwyn-davies">Bronwyn Davies</a></td></tr>
              </tbody>
            </table>
          </div>
        </main>
        """

        result = parse_faculty_page(
            html,
            "https://www.auckland.ac.nz/en/law/about-auckland-law-school/staff/academic-leadership.html",
        )

        self.assertEqual(result.candidate_count, 4)
        self.assertEqual(result.parsed_count, 4)
        self.assertEqual(
            [record.title for record in result.records],
            ["Acting Dean", "Acting Deputy Dean", "Associate Dean (Academic)", "Associate Dean (Curriculum, Teaching and Learning)"],
        )
        self.assertEqual(result.records[0].name, "Professor Susan Watson")
        self.assertEqual(result.records[0].profile_url, "https://profiles.auckland.ac.nz/s-watson")

    def test_extracts_uwa_grouped_accordion_staff_links(self):
        html = """
        <main>
          <dl class="accordion-masterbrand">
            <dt class="accordion-masterbrand__title">Professors</dt>
            <dd class="accordion-masterbrand__content">
              <ul>
                <li><a href="https://research-repository.uwa.edu.au/en/persons/alice-example">Alice Example</a></li>
                <li><a href="https://research-repository.uwa.edu.au/en/persons/bob-example">Bob Example</a></li>
              </ul>
            </dd>
            <dt class="accordion-masterbrand__title">Senior Lecturers</dt>
            <dd class="accordion-masterbrand__content">
              <ul>
                <li><a href="https://research-repository.uwa.edu.au/en/persons/carol-example">Carol Example</a></li>
              </ul>
            </dd>
          </dl>
        </main>
        """

        result = parse_faculty_page(html, "https://www.uwa.edu.au/schools/law/law-school-staff")

        self.assertEqual(result.possible_person_link_count, 3)
        self.assertEqual(result.candidate_count, 3)
        self.assertEqual(result.parsed_count, 3)
        self.assertEqual([record.name for record in result.records], ["Alice Example", "Bob Example", "Carol Example"])
        self.assertEqual([record.title for record in result.records], ["Professors", "Professors", "Senior Lecturers"])
        self.assertEqual(
            result.records[0].profile_url,
            "https://research-repository.uwa.edu.au/en/persons/alice-example",
        )

    def test_extracts_kth_split_name_directory_table_rows(self):
        html = """
        <main>
          <div class="kth-main-content container department standard with-local-nav">
            <table>
              <thead>
                <tr>
                  <th>Last Name</th>
                  <th>First Name</th>
                  <th>Title</th>
                  <th>Email</th>
                  <th>Phone</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td class="lastname"><a href="https://www.kth.se/profile/alovelace">Lovelace</a></td>
                  <td class="firstname"><a href="https://www.kth.se/profile/alovelace">Ada</a></td>
                  <td class="title">Professor</td>
                  <td class="email"><a href="mailto:ada@kth.se">ada@kth.se</a></td>
                  <td class="phone">123</td>
                </tr>
                <tr>
                  <td class="lastname"><a href="https://www.kth.se/profile/ghopper">Hopper</a></td>
                  <td class="firstname"><a href="https://www.kth.se/profile/ghopper">Grace</a></td>
                  <td class="title">Senior Lecturer</td>
                  <td class="email"><a href="mailto:grace@kth.se">grace@kth.se</a></td>
                  <td class="phone">456</td>
                </tr>
              </tbody>
            </table>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://www.arch.kth.se/en/om-oss/kontakt/medarbetare")

        self.assertEqual(result.possible_person_link_count, 2)
        self.assertEqual(result.page_type, "table")
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.parsed_count, 2)
        self.assertEqual([record.name for record in result.records], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual([record.title for record in result.records], ["Professor", "Senior Lecturer"])
        self.assertEqual(result.records[0].profile_url, "https://www.kth.se/profile/alovelace")

    def test_extracts_split_name_rows_with_linked_academic_abbreviations(self):
        html = """
        <main>
          <h1>Faculty</h1>
          <table>
            <thead><tr>
              <th>Last Name</th><th>First Name</th><th>Title</th><th>Email</th><th>Phone</th>
            </tr></thead>
            <tbody>
              <tr>
                <td><a href="/en/persons/peter-aebersold/"></a><a href="/en/persons/peter-aebersold/">Aebersold</a></td>
                <td><a href="/en/persons/peter-aebersold/">Peter</a></td>
                <td><a href="/en/persons/peter-aebersold/">Prof. Dr.</a></td>
                <td><a href="mailto:peter@example.edu">peter@example.edu</a></td><td></td>
              </tr>
              <tr>
                <td><a href="/en/persons/dario-ammann/">Ammann</a></td>
                <td><a href="/en/persons/dario-ammann/">Dario</a></td>
                <td><a href="/en/persons/dario-ammann/">PD Dr.iur.</a></td>
                <td><a href="mailto:dario@example.edu">dario@example.edu</a></td><td></td>
              </tr>
              <tr>
                <td><a href="/en/persons/no-title/">Person</a></td>
                <td><a href="/en/persons/no-title/">Untitled</a></td>
                <td></td><td><a href="mailto:untitled@example.edu">untitled@example.edu</a></td><td></td>
              </tr>
            </tbody>
          </table>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/en/people-list-faculty/")

        self.assertEqual(result.page_type, "table")
        self.assertEqual(result.table_rows_detected, 3)
        self.assertEqual(result.table_rows_parsed, 2)
        self.assertEqual(
            [(record.name, record.title, record.profile_url) for record in result.records],
            [
                ("Peter Aebersold", "Prof. Dr.", "https://example.edu/en/persons/peter-aebersold/"),
                ("Dario Ammann", "PD Dr.iur.", "https://example.edu/en/persons/dario-ammann/"),
            ],
        )

    def test_does_not_replace_valid_split_name_table_with_lower_coverage_segmented_links(self):
        rows = "".join(
            f"""
            <tr>
              <td><a href="/people/person-{index}">Surname{index}</a></td>
              <td><a href="/people/person-{index}">Given{index}</a></td>
              <td>{'Professor' if index <= 4 else ''}</td>
              <td><a href="mailto:p{index}@example.edu">p{index}@example.edu</a></td><td></td>
            </tr>
            """
            for index in range(1, 11)
        )
        mobile_links = "".join(
            f'<p><a href="/people/person-{index}">Given{index} Surname{index}</a></p>'
            for index in range(1, 11)
        )
        html = f"""
        <main>
          <table><thead><tr>
            <th>Last Name</th><th>First Name</th><th>Title</th><th>Email</th><th>Phone</th>
          </tr></thead><tbody>{rows}</tbody></table>
          {mobile_links}
          <p><a href="/jobs"><strong>Current Vacancies</strong><span>Professor</span></a></p>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/faculty/")

        self.assertEqual(result.table_rows_detected, 10)
        self.assertEqual(result.table_rows_parsed, 4)
        self.assertEqual(result.parsed_count, 4)
        self.assertEqual([record.name for record in result.records], [f"Given{i} Surname{i}" for i in range(1, 5)])

    def test_extracts_kit_physics_faculty_like_table_rows(self):
        html = """
        <main>
          <h2>Professors</h2>
          <table>
            <thead>
              <tr>
                <th><a href="?sort_table=22&sort_field=name&sort_order=SORT_ASC#block22">Name</a></th>
                <th><a href="?sort_table=22&sort_field=title&sort_order=SORT_ASC#block22">Title</a></th>
                <th>Institute</th>
                <th>E-Mail</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><a href="/english/department/person-detail.php?id=beckmann">Beckmann, Detlef</a></td>
                <td>apl. Prof. Dr.</td>
                <td>IQMT</td>
                <td>detlef dot beckmann at kit edu</td>
              </tr>
              <tr>
                <td><a href="/english/department/person-detail.php?id=bluhm">Bluhm, Hendrik</a></td>
                <td>Prof. Dr.</td>
                <td>PHI</td>
                <td>hendrik dot bluhm at kit edu</td>
              </tr>
            </tbody>
          </table>
        </main>
        """

        result = parse_faculty_page(html, "https://www.physik.kit.edu/english/department/persons.php")

        self.assertEqual(result.page_type, "table")
        self.assertGreater(result.parsed_count, 0)
        self.assertEqual([record.name for record in result.records], ["Beckmann, Detlef", "Bluhm, Hendrik"])
        self.assertEqual([record.title for record in result.records], ["apl. Prof. Dr.", "Prof. Dr."])
        self.assertTrue(all(record.profile_url != "https://www.physik.kit.edu/english/department/persons.php" for record in result.records))
        self.assertTrue(all("sort_table" not in record.profile_url for record in result.records))
        self.assertEqual(
            result.records[0].profile_url,
            "https://www.physik.kit.edu/english/department/person-detail.php?id=beckmann",
        )

    def test_extracts_cologne_full_professors_contact_table_rows(self):
        html = """
        <main>
          <h1>Full Professors</h1>
          <figure class="table">
            <table class="contenttable">
              <thead>
                <tr>
                  <th>Surname, first name</th>
                  <th>Phone number</th>
                  <th>E-mail address</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Avenarius, Dr. iur. Martin</td>
                  <td>+49 221 470-5688</td>
                  <td><a href="#" data-mailto-token="x">ius-romanum(at)uni-koeln(dot)de</a></td>
                </tr>
                <tr>
                  <td><a href="https://bankrecht.uni-koeln.de/en/lehrstuhl/lehrstuhlinhaber">Berger, Dr. iur. Klaus Peter</a></td>
                  <td>+49 221 470-2327</td>
                  <td><a href="#" data-mailto-token="x">post(at)bankrecht-koeln(dot)de</a></td>
                </tr>
                <tr>
                  <td>Not A Person</td>
                  <td></td>
                  <td></td>
                </tr>
              </tbody>
            </table>
          </figure>
        </main>
        """

        result = parse_faculty_page(html, "https://jura.uni-koeln.de/en/fakultaet/personen/full-professors")

        self.assertEqual(result.page_type, "table")
        self.assertEqual(result.table_rows_detected, 3)
        self.assertEqual(result.table_rows_parsed, 1)
        self.assertEqual(result.candidate_count, 3)
        self.assertEqual(result.parsed_count, 1)
        self.assertEqual(
            [record.name for record in result.records],
            ["Berger, Dr. iur. Klaus Peter"],
        )
        self.assertEqual([record.title for record in result.records], ["Full Professor"])
        self.assertEqual(
            result.records[0].profile_url,
            "https://bankrecht.uni-koeln.de/en/lehrstuhl/lehrstuhlinhaber",
        )
        self.assertIn("missing_profile_url", [debug["drop_reason"] for debug in result.dropped_candidate_debug])

    def test_runs_linked_cards_and_unlinked_table_rows_on_one_page(self):
        faculty_people = [
            ("Ada Adams", "Professor"),
            ("Bryn Baker", "Associate Professor"),
            ("Cleo Carter", "Assistant Professor"),
            ("Drew Diaz", "Professor"),
            ("Emery Evans", "Associate Professor"),
            ("Flynn Foster", "Assistant Professor"),
            ("Gray Garcia", "Professor"),
            ("Harper Harris", "Associate Professor"),
            ("Indigo Irving", "Assistant Professor"),
            ("Jordan Jones", "Professor"),
            ("Kai Kim", "Associate Professor"),
            ("Lane Lewis", "Professor Emeritus"),
        ]
        faculty_cards = "".join(
            f"""
            <article class="person-card">
              <a class="person-name" href="https://researchportal.example.org/person/{index}">{name}</a>
              <span class="person-title">{title}</span>
              <a href="mailto:person{index}@example.edu">person{index}@example.edu</a>
            </article>
            """
            for index, (name, title) in enumerate(faculty_people, start=1)
        )
        adjunct_rows = "".join(
            f"""
            <tr>
              <td><span class="person-name">Adjunct Person {index}</span></td>
              <td>Adjunct Professor</td>
              <td>adjunct{index}@example.edu</td>
              <td>555-010{index}</td>
            </tr>
            """
            for index in range(1, 5)
        )
        html = f"""
        <main>
          <section>
            <h2>Faculty</h2>
            <div class="people-list">{faculty_cards}</div>
          </section>
          <section>
            <h2>Adjunct Faculty</h2>
            <table>
              <thead>
                <tr><th>Name</th><th>Title</th><th>Email</th><th>Phone</th></tr>
              </thead>
              <tbody>{adjunct_rows}</tbody>
            </table>
          </section>
          <section>
            <h2>Administrative Staff</h2>
            <article class="person-card">
              <a class="person-name" href="https://researchportal.example.org/person/admin">Alex Admin</a>
              <span class="person-title">Professor</span>
            </article>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/academics/sociology/people")

        self.assertEqual(result.page_type, "table")
        self.assertEqual(result.table_rows_detected, 4)
        self.assertEqual(result.table_rows_parsed, 0)
        self.assertEqual(result.candidate_count, 17)
        self.assertEqual(result.parsed_count, 11)
        self.assertEqual([record.name for record in result.records], [name for name, _ in faculty_people[:-1]])
        self.assertTrue(all(record.profile_url.startswith("https://researchportal.example.org/person/") for record in result.records))
        self.assertNotIn("Lane Lewis", [record.name for record in result.records])
        self.assertNotIn("Alex Admin", [record.name for record in result.records])
        adjunct_drops = [
            item for item in result.dropped_candidate_debug if item["raw_text"].startswith("Adjunct Person")
        ]
        self.assertEqual(len(adjunct_drops), 4)
        self.assertTrue(all(item["drop_reason"] == "missing_profile_url" for item in adjunct_drops))
        self.assertTrue(all(item["section_heading"] == "Adjunct Faculty" for item in adjunct_drops))
        self.assertNotIn("Phone", [item["section_heading"] for item in adjunct_drops])

    def test_extracts_copenhagen_law_research_staff_rows_without_profile_links(self):
        html = """
        <main>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Title</th>
                <th>Job responsibilities</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><a href="/english/staff/research/?pure=en/persons/anna-andersen">Anna Andersen</a></td>
                <td>Professor</td>
                <td>EU law and public procurement</td>
              </tr>
              <tr>
                <td>Bo Berg</td>
                <td>Associate Professor</td>
                <td>Legal theory</td>
              </tr>
              <tr>
                <td><a href="/english/staff/research/">Carla Christensen</a><a href="#top">Top</a></td>
                <td>Assistant Professor</td>
                <td>Private law</td>
              </tr>
              <tr>
                <td><a href="/english/staff/research/?pure=en/persons/diana-dahl">Diana Dahl</a></td>
                <td>Professor</td>
                <td>Tax law</td>
              </tr>
              <tr>
                <td><a href="/english/staff/research/?pure=en/persons/erik-eriksen">Erik Eriksen</a></td>
                <td>Student FU</td>
                <td>Student assistant tasks</td>
              </tr>
            </tbody>
          </table>
        </main>
        """

        result = parse_faculty_page(html, "https://jura.ku.dk/english/staff/research/")

        self.assertEqual(result.page_type, "table")
        self.assertEqual(result.candidate_count, 5)
        self.assertEqual(result.parsed_count, 4)
        self.assertEqual([record.name for record in result.records], ["Anna Andersen", "Bo Berg", "Carla Christensen", "Diana Dahl"])
        self.assertEqual([record.title for record in result.records], ["Professor", "Associate Professor", "Assistant Professor", "Professor"])
        self.assertEqual(
            result.records[0].profile_url,
            "https://jura.ku.dk/english/staff/research/?pure=en/persons/anna-andersen",
        )
        self.assertEqual(result.records[1].profile_url, "")
        self.assertEqual(result.records[2].profile_url, "")
        self.assertEqual(
            result.records[3].profile_url,
            "https://jura.ku.dk/english/staff/research/?pure=en/persons/diana-dahl",
        )

    def test_drops_bonn_law_teaching_staff_category_blocks(self):
        html = """
        <main>
          <h1>Professors and lecturers in the Department of Law</h1>
          <section>
            <h2>Public Law</h2>
            <div class="faculty-card">
              <a href="/en/research-and-teaching/teaching-staff/teaching-staff-1">Associate Professors</a>
              <a href="/de/forschung-und-lehre/lehrende-personenverzeichnis/apl-professor-innen">Senior Professors</a>
              <a href="/de/forschung-und-lehre/lehrende-personenverzeichnis/honorarprofessor-innen">Honorary Professors</a>
              <a href="/de/forschung-und-lehre/lehrende-personenverzeichnis/lehrbeauftragte">Lecturers</a>
              <a href="/de/forschung-und-lehre/lehrende-personenverzeichnis/emeriti">Emeriti</a>
            </div>
          </section>
          <section>
            <h2>Criminal Law</h2>
            <div class="faculty-card">
              <h3><a href="/en/people/ada-lovelace">Ada Lovelace</a></h3>
              <p>Professor of Law</p>
            </div>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://www.jura.uni-bonn.de/en/research-and-teaching/teaching-staff")

        self.assertEqual([record.name for record in result.records], ["Ada Lovelace"])
        self.assertNotIn("Associate Professors", [record.name for record in result.records])
        self.assertIn(
            "navigation_or_category_block",
            [debug["drop_reason"] for debug in result.dropped_candidate_debug],
        )
        self.assertTrue(any("possible_directory_index_page" in item for item in result.href_patterns_debug))

    def test_staff_section_is_neutral_but_administrative_and_emeritus_sections_are_excluded(self):
        html = """
        <main>
          <section><h2>Staff</h2><div class="person-card"><h3><a href="/staff/eleanor-balchin">Dr Eleanor Balchin</a></h3><p>Reader in Social Policy</p></div></section>
          <section><h2>Our Staff</h2><div class="person-card"><h3><a href="/staff/chloe-blackwell">Dr Chloe Blackwell</a></h3><p>Senior Lecturer</p></div></section>
          <section><h2>People</h2><div class="person-card"><h3><a href="/staff/ann-browning">Ann Browning</a></h3><p>University Teacher</p></div></section>
          <section><h2>Faculty and Staff</h2><div class="person-card"><h3><a href="/staff/john-coxhead">Dr John Coxhead</a></h3><p>Senior Research Fellow</p></div></section>
          <section><h2>Staff</h2><div class="person-card"><h3><a href="/staff/pat-coordinator">Pat Coordinator</a></h3><p>Programme Coordinator</p></div></section>
          <section><h2>Administrative Staff</h2><div class="person-card"><h3><a href="/staff/alex-admin">Alex Admin</a></h3><p>Visiting Professor</p></div></section>
          <section><h2>Emeritus Faculty</h2><div class="person-card"><h3><a href="/staff/erin-emeritus">Erin Emeritus</a></h3><p>Professor</p></div></section>
        </main>
        """

        result = parse_faculty_page(html, "https://www.lboro.ac.uk/subjects/social-policy-studies/staff/")

        self.assertEqual(
            [record.name for record in result.records],
            ["Dr Eleanor Balchin", "Dr Chloe Blackwell", "Ann Browning", "Dr John Coxhead"],
        )
        self.assertNotIn("Pat Coordinator", [record.name for record in result.records])
        self.assertNotIn("Alex Admin", [record.name for record in result.records])
        self.assertNotIn("Erin Emeritus", [record.name for record in result.records])

    def test_recovers_trusted_external_profiles_ignores_card_headings_and_merges_duplicates(self):
        html = """
        <main>
          <section>
            <h2>Docentes</h2>
            <div class="person-card">
              <h3>Maria Silva</h3>
              <p>Associate Professor</p>
              <h4>Piso 2 - Gabinete 19 - Bloco Tejo</h4>
              <a href="https://www.cienciavitae.pt/portal/ABCD-1234">Ciência Vitae</a>
            </div>
            <div class="person-card">
              <h3>Maria Silva</h3>
              <p>Associate Professor</p>
              <a href="mailto:maria.silva@ulisboa.pt">maria.silva@ulisboa.pt</a>
              <a href="https://www.cienciavitae.pt/portal/ABCD-1234">Profile</a>
            </div>
            <div class="person-card">
              <h3>Ana Santos</h3>
              <p>Lecturer</p>
              <a href="mailto:ana.santos@ulisboa.pt">ana.santos@ulisboa.pt</a>
              <a href="https://example.com/ana-santos">Personal link</a>
            </div>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://www.iscsp.ulisboa.pt/pt/sociologia")

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].name, "Maria Silva")
        self.assertEqual(result.records[0].profile_url, "https://www.cienciavitae.pt/portal/ABCD-1234")
        self.assertEqual(result.records[0].email, "maria.silva@ulisboa.pt")
        self.assertEqual(result.dropped_candidate_debug[0]["section_heading"], "Docentes")

    def test_accepts_only_trusted_external_academic_profile_domains_inside_cards(self):
        html = """
        <main>
          <div class="person-card"><h3>Ada Lovelace</h3><p>Professor</p><a href="https://orcid.org/0000-0002-1825-0097">ORCID</a></div>
          <div class="person-card"><h3>Grace Hopper</h3><p>Professor</p><a href="https://researchportal.example.edu/en/persons/grace-hopper">Research portal</a></div>
          <div class="person-card"><h3>Radia Perlman</h3><p>Professor</p><a href="https://example.elsevierpure.com/en/persons/radia-perlman">Pure profile</a></div>
          <div class="person-card"><h3>Jane Manager</h3><p>Professor</p><a href="mailto:jane@example.edu">jane@example.edu</a><a href="https://example.com/jane">External site</a></div>
        </main>
        """

        records = parse_faculty_page(html, "https://university.example.edu/staff").records

        self.assertEqual([record.name for record in records], ["Ada Lovelace", "Grace Hopper", "Radia Perlman"])

    def test_recovers_trusted_profile_from_following_siblings_until_next_person_boundary(self):
        html = """
        <main>
          <div class="person-card"><h3>Paula Campos Pinto</h3><p>Associate Professor</p><a href="mailto:paula@ulisboa.pt">paula@ulisboa.pt</a></div>
          <div class="contact-block">Telefone: 213 600 000</div>
          <div class="profile-block"><a href="https://www.cienciavitae.pt/portal/6217-DF2D-CC1D">Ciência Vitae</a></div>
          <div class="person-card"><h3>Maria da Luz Ramos</h3><p>Lecturer</p><a href="mailto:maria@ulisboa.pt">maria@ulisboa.pt</a></div>
          <div class="contact-block"><h4>Piso 0 - Gabinete 30 - Bloco Tejo</h4></div>
          <div class="profile-block"><a href="https://cienciavitae.pt/pt/EB1B-E42A-F713">Ciência Vitae</a></div>
          <div class="person-card"><h3>Ana Santos</h3><p>Professor</p><a href="mailto:ana@ulisboa.pt">ana@ulisboa.pt</a></div>
          <div class="person-card"><h3>Next Person</h3><p>Professor</p><a href="https://orcid.org/0000-0002-1825-0097">ORCID</a></div>
        </main>
        """

        result = parse_faculty_page(html, "https://www.iscsp.ulisboa.pt/pt/sociologia")

        self.assertEqual(
            [(record.name, record.profile_url) for record in result.records],
            [
                ("Paula Campos Pinto", "https://www.cienciavitae.pt/portal/6217-DF2D-CC1D"),
                ("Maria da Luz Ramos", "https://cienciavitae.pt/pt/EB1B-E42A-F713"),
                ("Next Person", "https://orcid.org/0000-0002-1825-0097"),
            ],
        )
        self.assertGreater(result.card_recovered_profile_links_count, 0)
        self.assertEqual(result.card_profile_link_debug[0]["profile_search_scope"], "following_siblings")
        self.assertEqual(result.card_profile_link_debug[0]["scanned_sibling_count"], 2)
        self.assertEqual(result.card_profile_link_debug[2]["stop_boundary"], "next_person_card")

    def test_parses_legacy_stref_profile_links_with_adjacent_academic_titles(self):
        html = """
        <main><ul>
          <li><p><a href="/massey/expertise/profile.cfm?stref=991040">Professor Glenn Banks</a></p><p>Professor - <i>School of People, Environment and Planning</i></p></li>
          <li><p><a href="/massey/expertise/profile.cfm?stref=161402">Associate Professor Alice Beban</a></p><p>Associate Professor - <i>School of People, Environment and Planning</i></p></li>
          <li><p><a href="/massey/expertise/profile.cfm?stref=982350">Dr Peter Howland</a></p><p>Senior Lecturer in Sociology - <i>School of People, Environment and Planning</i></p><p>Ph: 1234</p></li>
          <li><p><a href="/massey/expertise/profile.cfm?stref=000001">Jane Manager</a></p><p>Programme Manager</p></li>
        </ul></main>
        """

        result = parse_faculty_page(html, "https://www.massey.ac.nz/massey/expertise/staff-list.cfm")

        self.assertEqual(
            [(record.name, record.title) for record in result.records],
            [
                ("Professor Glenn Banks", "Professor"),
                ("Associate Professor Alice Beban", "Associate Professor"),
                ("Dr Peter Howland", "Senior Lecturer in Sociology"),
            ],
        )
        self.assertEqual(len({record.profile_url for record in result.records}), 3)
        self.assertTrue(all("profile.cfm?stref=" in record.profile_url for record in result.records))

    def test_parses_heading_name_cards_with_generic_profile_links(self):
        html = """
        <main>
          <h1>Docentes</h1>
          <div><div><h5>Arlete Moyses Rodrigues</h5></div><div>Docente</div><div><a href="/pessoas/arlete-moyses-rodrigues">ver perfil</a></div></div>
          <div><div><h6>Bárbara Geraldo de Castro</h6></div><div>Docente</div><div><a href="/pessoas/barbara-geraldo-de-castro">more details</a></div></div>
          <nav><a href="?page=1" rel="next">Próximo</a></nav>
        </main>
        """

        result = parse_faculty_page(html, "https://www.ifch.unicamp.br/pos/sociologia/pessoas/docentes")

        self.assertEqual([record.name for record in result.records], ["Arlete Moyses Rodrigues", "Bárbara Geraldo de Castro"])
        self.assertTrue(all(record.title == "Docente" for record in result.records))
        self.assertNotIn("ver perfil", [record.name.lower() for record in result.records])
        self.assertEqual(result.heading_card_candidates_count, 2)
        self.assertEqual(result.generic_profile_links_count, 2)
        self.assertEqual(result.heading_card_debug[0]["candidate_name"], "Arlete Moyses Rodrigues")
        self.assertEqual(
            find_next_directory_page_url(html, "https://www.ifch.unicamp.br/pos/sociologia/pessoas/docentes"),
            "https://www.ifch.unicamp.br/pos/sociologia/pessoas/docentes?page=1",
        )

    def test_parses_role_grouped_person_rows_with_unique_query_profiles(self):
        html = """
        <main>
          <nav><a href="/category/ruoli/professore-emerito">Professore emerito</a></nav>
          <h2>Personale docente</h2>
          <h3>Professore ordinario</h3>
          <ul>
            <li><a href="/category/ruoli/personale-docente?key=00C57F633B98B3546591BCBA6573A853">STEFANO ALLIEVI 0498274357</a> stefano.allievi@unipd.it</li>
            <li><a href="/category/ruoli/personale-docente?key=3ACE72FE6D9D70362DEA4E419E7E28B6">CHIARA BIASIN 0498271736</a></li>
          </ul>
          <h3>Professore associato</h3>
          <ul><li><a href="/category/ruoli/personale-docente?key=ABC123">GIORGIO OSTI</a></li></ul>
          <h3>Personale amministrativo</h3>
          <ul><li><a href="/category/ruoli/personale-docente?key=ADMIN1">ADMIN USER</a></li></ul>
        </main>
        """

        result = parse_faculty_page(html, "https://www.fisppa.unipd.it/category/ruoli/personale-docente")

        self.assertEqual([record.name for record in result.records], ["STEFANO ALLIEVI", "CHIARA BIASIN", "GIORGIO OSTI"])
        self.assertEqual([record.title for record in result.records], ["Professore ordinario", "Professore ordinario", "Professore associato"])
        self.assertTrue(all("?key=" in record.profile_url for record in result.records))
        self.assertEqual(result.role_group_count, 2)
        self.assertEqual(result.person_rows_detected, 3)
        self.assertEqual(result.role_group_debug[0]["inherited_role_title"], "Professore ordinario")

    def test_builds_local_people_from_repeated_listing_subpage_links_and_excludes_emeritus(self):
        html = """
        <main>
          <h1>Academic Staff</h1>
          <div class="faculty-list">
            <h5>Professor</h5>
            <div><a href="/people/academic-staff/koo-anita.html"><img alt=""></a><h6><a href="/people/academic-staff/koo-anita.html">KOO, Anita C.H.</a></h6><p>Research Interests</p></div>
            <h5>Associate Professor</h5>
            <div><a href="/people/academic-staff/chan-kwok-shing.html"><img alt=""></a><h6><a href="/people/academic-staff/chan-kwok-shing.html">CHAN, Kwok Shing</a></h6></div>
            <h5>Emeritus Professor</h5>
            <div><a href="/people/academic-staff/barbalet-jack.html"><img alt=""></a><h6><a href="/people/academic-staff/barbalet-jack.html">BARBALET, Jack</a></h6></div>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://socweb.hkbu.edu.hk/people/academic-staff.html")

        self.assertEqual([record.name for record in result.records], ["KOO, Anita C.H.", "CHAN, Kwok Shing"])
        self.assertEqual([record.title for record in result.records], ["Professor", "Associate Professor"])
        self.assertEqual(result.faculty_profile_links_detected, 6)
        self.assertEqual(result.unique_profile_links_count, 3)
        self.assertEqual(result.local_person_blocks_created, 2)
        self.assertEqual(result.duplicate_profile_links_count, 3)
        self.assertEqual(result.excluded_section_count, 1)
        self.assertEqual(result.candidate_count, 2)

    def test_segments_many_linked_people_inside_one_large_faculty_wrapper(self):
        html = """
        <main>
          <h1>Faculty</h1>
          <div class="faculty-wrapper">
            <a href="/sociology/bio/joe-bandy-sociology"><img alt=""></a>
            <a href="/sociology/bio/joe-bandy-sociology">Joe Bandy</a>
            <p>Associate Professor of the Practice in Culture, Advocacy, and Leadership</p>
            <p>Associate Professor of the Practice in Sociology</p>
            <a href="mailto:joe@example.edu">Email</a><a href="https://example.com">Website</a>
            <a href="/sociology/bio/laura-carpenter">Laura M. Carpenter</a>
            <p>Associate Professor of Sociology</p>
            <a href="/sociology/bio/andre-christie-mizell">C. André Christie-Mizell</a>
            <p>Professor of Sociology</p><p>Centennial Professor of Sociology</p>
            <a href="/sociology/bio/no-title">Person Without Title</a>
            <a href="/sociology/bio/no-title-2">Second Person Without Title</a>
            <a href="/sociology/bio/no-title-3">Third Person Without Title</a>
            <a href="/sociology/bio/no-title-4">Fourth Person Without Title</a>
            <a href="/sociology/bio/no-title-5">Fifth Person Without Title</a>
            <a href="/sociology/bio/no-title-6">Sixth Person Without Title</a>
            <a href="/sociology/bio/no-title-7">Seventh Person Without Title</a>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://as.vanderbilt.edu/sociology/people/")

        self.assertEqual(
            [record.name for record in result.records],
            ["Joe Bandy", "Laura M. Carpenter", "C. André Christie-Mizell"],
        )
        self.assertEqual(result.records[0].title, "Associate Professor of the Practice in Sociology")
        self.assertEqual(len({record.profile_url for record in result.records}), 3)
        self.assertEqual(result.wrapper_person_links_count, 10)
        self.assertEqual(result.segmented_person_blocks_count, 10)
        self.assertEqual(result.segmented_person_debug[0]["block_name"], "Joe Bandy")
        self.assertEqual(result.segmented_person_debug[0]["selected_title"], "Associate Professor of the Practice in Sociology")
        self.assertEqual(result.segmented_person_debug[3]["reject_reason"], "missing_title")

    def test_splits_valid_spanish_academic_titles_inside_segmented_person_blocks(self):
        html = """
        <main>
          <h1>Faculty</h1>
          <div class="faculty-wrapper">
            <a href="/people/person-one">Person Name Profesor asociado</a>
            <a href="/people/person-two">Person Name Two Profesora asistente</a>
            <a href="/people/person-three">Person Name Three Profesor titular</a>
            <a href="/people/person-four"><h3>Person Name Four</h3><span>Profesora auxiliar</span></a>
            <a href="/people/person-five">Person Name Five</a>
            <p>Programme coordinator</p>
            <a href="/people/person-six">Person Name Six Biography</a>
            <a href="/people/person-seven">Person Name Seven</a>
            <a href="/people/person-eight">Person Name Eight</a>
            <a href="/people/person-nine">Person Name Nine</a>
            <a href="/people/person-ten">Person Name Ten</a>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/faculty/")

        self.assertEqual(
            [(record.name, record.title, record.profile_url) for record in result.records],
            [
                ("Person Name", "Profesor asociado", "https://example.edu/people/person-one"),
                ("Person Name Two", "Profesora asistente", "https://example.edu/people/person-two"),
                ("Person Name Three", "Profesor titular", "https://example.edu/people/person-three"),
                ("Person Name Four", "Profesora auxiliar", "https://example.edu/people/person-four"),
            ],
        )
        debug_by_name = {item["block_name"]: item for item in result.segmented_person_debug}
        self.assertEqual(debug_by_name["Person Name Five"]["reject_reason"], "missing_title")
        self.assertEqual(debug_by_name["Person Name Six Biography"]["reject_reason"], "missing_title")

    def test_extracts_structured_catalan_academic_teasers_with_query_profiles(self):
        html = """
        <body>
          <h1>Professorat de la Facultat</h1>
          <div class="row">
            <div class="indexinvestigadors"><a href="Biologia.html?id=abril&amp;lang=ca">
              <img alt="Josep Francesc Abril Ferrando"><div class="dadesinv">
                <h4 class="nominv">Josep Francesc Abril Ferrando</h4><div class="textinv">Professor Agregat</div>
              </div>
            </a></div>
            <div class="indexinvestigadors"><a href="Biologia.html?id=aguado&amp;lang=ca">
              <img alt="Fernando Aguado Tomas"><div class="dadesinv">
                <h4 class="nominv">Fernando Aguado Tomas</h4><div class="textinv">Catedràtic d'Universitat</div>
              </div>
            </a></div>
            <div class="indexinvestigadors"><a href="Biologia.html?id=real&amp;lang=ca">
              <img alt="Joan Real Orti"><div class="dadesinv">
                <h4 class="nominv">Joan Real Orti</h4><div class="textinv">Titular d'Universitat</div>
              </div>
            </a></div>
            <div class="indexinvestigadors"><a href="Biologia.html?id=ramirez&amp;lang=ca">
              <img alt="Iván Ramírez Pedraza"><div class="dadesinv">
                <h4 class="nominv">Iván Ramírez Pedraza</h4><div class="textinv">Investigador Juan de la Cierva</div>
              </div>
            </a></div>
          </div>
          <nav><a href="Biologia.html?category=research">Research categories</a></nav>
          <footer><div class="row content">Social links</div></footer>
        </body>
        """

        result = parse_faculty_page(html, "https://example.edu/fitxes/index.html?id=11&amp;lang=ca")

        self.assertEqual(result.candidate_count, 4)
        self.assertEqual(result.parsed_count, 4)
        self.assertEqual(
            [(record.name, record.title) for record in result.records],
            [
                ("Josep Francesc Abril Ferrando", "Professor Agregat"),
                ("Fernando Aguado Tomas", "Catedràtic d'Universitat"),
                ("Joan Real Orti", "Titular d'Universitat"),
                ("Iván Ramírez Pedraza", "Investigador Juan de la Cierva"),
            ],
        )
        self.assertEqual(len({record.profile_url for record in result.records}), 4)

    def test_segments_every_trusted_profile_row_before_section_and_emeritus_filtering(self):
        academic_people = [
            ("Dr Paul Bermingham", "Teaching Fellow"),
            ("Professor John Bone", "Personal Chair"),
            ("Professor Steve Bruce", "Emeritus Professor of Sociology"),
            ("Dr Sonja Erikainen", "Lecturer"),
            ("Dr Luisa Gandolfo", "Senior Lecturer"),
            ("Professor Bernadette Hayes", "Emerita Professor in Sociology"),
            ("Dr Isabella Kasselstrand", "Senior Lecturer"),
            ("Dr Christopher Kollmeyer", "Senior Lecturer and Head of Department"),
            ("Dr Andrew McKinnon", "Senior Lecturer"),
            ("Professor Gearoid Millar", "Personal Chair"),
            ("Dr Peter Olayiwola", "Lecturer in Sociology"),
            ("Dr Norman Stockman", "Emeritus Senior Lecturer"),
            ("Professor Claire Wallace", "Chair in Sociology"),
            ("Dr Rhoda Wilkie", "Senior Lecturer"),
        ]
        academic_rows = "".join(
            f'<tr><td><a href="/people/person-{index}">{name}</a><br>{title}</td>'
            f'<td>+44 1224 {index:06d}</td><td><a href="mailto:p{index}@example.edu">p{index}@example.edu</a></td></tr>'
            for index, (name, title) in enumerate(academic_people)
        )
        administrative_rows = "".join(
            f'<tr><td><a href="/people/admin-{index}">{name}</a></td><td>+44 1224 000000</td>'
            f'<td><a href="mailto:a{index}@example.edu">Email</a></td></tr>'
            for index, name in enumerate(("Mrs Kerry Boyne", "Ms Jill Davis", "Mrs Pam Thomson"))
        )
        html = f"""
        <main><div class="directory-wrapper">
          <h2>Academic Staff</h2>
          <table><thead><tr><th>Name</th><th>Telephone</th><th>Email</th></tr></thead>
            <tbody>{academic_rows}</tbody></table>
          <h2>Administrative Staff</h2>
          <table><thead><tr><th>Name</th><th>Telephone</th><th>Email</th></tr></thead>
            <tbody>{administrative_rows}</tbody></table>
        </div></main>
        """

        result = parse_faculty_page(html, "https://example.edu/sociology/staff/")

        self.assertEqual(result.wrapper_person_links_count, 17)
        self.assertEqual(result.segmented_person_blocks_count, 17)
        self.assertEqual(result.segmented_academic_section_count, 14)
        self.assertEqual(result.segmented_administrative_exclusion_count, 3)
        self.assertEqual(result.segmented_emeritus_exclusion_count, 3)
        self.assertEqual(result.parsed_count, 11)
        self.assertEqual(
            [(record.name, record.title) for record in result.records],
            [item for item in academic_people if "Emerit" not in item[1]],
        )
        self.assertEqual(len({record.profile_url for record in result.records}), 11)
        self.assertNotIn("Professor John Bone", [record.title for record in result.records])
        self.assertEqual(result.records[0].email, "p0@example.edu")

    def test_segments_same_institution_academic_list_items_with_prefix_titles(self):
        groups = [
            ("Professors", [
                ("Head of Department", "Professor Ada Lovelace", "ada-lovelace"),
                ("Professor of Psychology", "Professor Grace Hopper", "grace-hopper"),
            ]),
            ("Readers", [
                ("", "Dr Katherine Johnson", "katherine-johnson"),
                ("", "Dr Barbara Liskov", "barbara-liskov"),
                ("", "Dr Frances Allen", "frances-allen"),
                ("", "Dr Margaret Hamilton", "margaret-hamilton"),
                ("", "Dr Karen Jones", "karen-jones"),
                ("", "Dr Mary Cartwright", "mary-cartwright"),
            ]),
            ("Clinical/Research/Teaching Fellows and Associates", [
                ("Postdoctoral Researcher", "Ms Abigail Pickard", "abigail-pickard"),
                ("Clinical Fellow", "Dr Frank Pearson", "frank-pearson"),
                ("Research Assistant", "Mr Levi Bentley", "levi-bentley"),
                ("Emeritus Professor", "Professor Paul Furlong", "paul-furlong"),
            ]),
        ]
        rows = "".join(
            f'<p><strong>{group}</strong></p><ul>'
            + "".join(
                f'<li>{f"({title}) " if title else ""}<a href="https://research.example.edu/en/persons/{slug}">{name}</a></li>'
                for title, name, slug in entries
            )
            + "</ul>"
            for group, entries in groups
        )
        html = f"""
        <body class="eu-cookie-compliance-popup-open">
          <main>
            <h3>Head of Department: <a href="https://research.example.edu/en/persons/ada-lovelace">Professor Ada Lovelace</a></h3>
            <h2>Academic staff</h2>
            <dl class="accordion"><dd>{rows}</dd></dl>
          </main>
        </body>
        """

        result = parse_faculty_page(html, "https://www.example.edu/psychology/staff")

        self.assertEqual(result.candidate_count, 12)
        self.assertEqual(result.wrapper_person_links_count, 12)
        self.assertEqual(result.parsed_count, 10)
        self.assertEqual(result.records[0].title, "Professors")
        self.assertEqual(result.records[2].title, "Readers")
        self.assertEqual(result.records[8].title, "Clinical/Research/Teaching Fellows and Associates")
        self.assertEqual(result.records[9].title, "Clinical/Research/Teaching Fellows and Associates")
        self.assertEqual(len({record.profile_url for record in result.records}), 10)
        self.assertNotIn("Mr Levi Bentley", [record.name for record in result.records])
        self.assertNotIn("Professor Paul Furlong", [record.name for record in result.records])

    def test_segments_several_people_inside_one_shared_table_cell(self):
        html = """
        <main><h2>Academic Staff</h2><table><tbody><tr><td>
          <a href="/people/alex-one">Dr Alex One</a><br>Lecturer<br>
          <a href="/people/beth-two">Professor Beth Two</a><br>Personal Chair<br>
          <a href="/people/cara-three">Dr Cara Three</a><br>Senior Lecturer
          <a href="/people/filler-four">Dr Filler Four</a><br>Emeritus Professor
          <a href="/people/filler-five">Dr Filler Five</a><br>Emerita Professor
          <a href="/people/filler-six">Dr Filler Six</a><br>Emeritus Senior Lecturer
          <a href="/people/filler-seven">Dr Filler Seven</a><br>Programme Coordinator
          <a href="/people/filler-eight">Dr Filler Eight</a><br>Programme Coordinator
          <a href="/people/filler-nine">Dr Filler Nine</a><br>Programme Coordinator
          <a href="/people/filler-ten">Dr Filler Ten</a><br>Programme Coordinator
        </td></tr></tbody></table></main>
        """

        result = parse_faculty_page(html, "https://example.edu/sociology/staff/")

        self.assertEqual(
            [(record.name, record.title) for record in result.records],
            [("Dr Alex One", "Lecturer"), ("Professor Beth Two", "Personal Chair"), ("Dr Cara Three", "Senior Lecturer")],
        )
        self.assertEqual(result.wrapper_person_links_count, 10)
        self.assertEqual(result.segmented_person_blocks_count, 10)

    def test_recovers_single_person_profile_from_wrapping_ancestor_anchor(self):
        html = """
        <main><div class="directory">
          <a href="/employees/ada-lovelace"><div class="result-item">
            <strong class="fullname">Ada Lovelace</strong>
            <span class="role">Professor</span>
            <span>ada@example.edu</span>
          </div></a>
        </div></main>
        """

        result = parse_faculty_page(html, "https://example.edu/sociology/")

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].name, "Ada Lovelace")
        self.assertEqual(result.records[0].title, "Professor")
        self.assertEqual(result.records[0].profile_url, "https://example.edu/employees/ada-lovelace")
        self.assertEqual(result.ancestor_profile_links_recovered_count, 1)
        self.assertEqual(result.unresolved_cards_missing_profile_url_count, 0)

    def test_repeated_linked_teasers_accept_chair_urls_and_strip_image_credit(self):
        html = """
        <body class="uma-faculty-site test-nav">
        <main><div id="page-content" class="page-content">
          <h1>Professors</h1>
          <section class="uma-address-menu">
            <a href="/chair/cognitive-psychology">
              <figure><figcaption>Credit: Jane Photographer</figcaption></figure>
              <div class="uma-address-name">Prof. Dr. Ada Lovelace</div>
              <div class="uma-address-title">Chair of Cognitive Psychology</div>
              <div class="uma-address-position">Professor for Cognitive Psychology</div>
            </a>
            <a href="/professorship/social-cognition">
              <figure><figcaption>Image: University archive</figcaption></figure>
              <div class="uma-address-name">Prof. Dr. Grace Hopper</div>
              <div class="uma-address-title">Professorship of Social Cognition</div>
            </a>
            <a href="/research/decision-science">
              <figure><figcaption>Photo: Computing archive</figcaption></figure>
              <div class="uma-address-name">Professor Katherine Johnson</div>
            </a>
          </section>
        </div></main>
        </body>
        """

        result = parse_faculty_page(html, "https://example.edu/department/psychology")

        self.assertEqual(
            [(record.name, record.title, record.profile_url) for record in result.records],
            [
                (
                    "Prof. Dr. Ada Lovelace",
                    "Chair of Cognitive Psychology",
                    "https://example.edu/chair/cognitive-psychology",
                ),
                (
                    "Prof. Dr. Grace Hopper",
                    "Professorship of Social Cognition",
                    "https://example.edu/professorship/social-cognition",
                ),
                (
                    "Professor Katherine Johnson",
                    "Professor",
                    "https://example.edu/research/decision-science",
                ),
            ],
        )
        self.assertTrue(all(not record.name.startswith(("Credit", "Image")) for record in result.records))

    def test_linked_teaser_fallback_is_bounded_to_repeated_main_professor_cards(self):
        names = [
            "Ada Lovelace",
            "Grace Hopper",
            "Alan Turing",
            "Katherine Johnson",
            "Edsger Dijkstra",
            "Barbara Liskov",
            "Donald Knuth",
            "Margaret Hamilton",
            "Claude Shannon",
            "John McCarthy",
            "Frances Allen",
            "Niklaus Wirth",
            "Karen Sparck Jones",
            "Marvin Minsky",
            "Mary Cartwright",
        ]
        cards = "".join(
            f"""
            <a class="linked-teaser" href="/chairs/research-area-{index}">
              <span>Credit: Photographer {index}</span>
              <h2>Prof. Dr. {name}</h2>
              <p>Chair of Research Area {index}</p>
            </a>
            """
            for index, name in enumerate(names, start=1)
        )
        html = f"""
        <header><a href="/chairs/navigation">Prof. Dr. Navigation Person</a></header>
        <main>
          <section class="professor-list">{cards}</section>
          <section class="category-teasers">
            <a href="/categories/professors"><h2>Professor Categories</h2><p>Chair directory</p></a>
            <a href="/department"><h2>Department Psychology</h2><p>Professorships</p></a>
          </section>
          <section class="promotions"><a href="/chairs/news"><img src="news.jpg" alt="Professor news"></a></section>
          <p>Deputy Professorships</p>
        </main>
        <footer><a href="/chairs/footer"><h2>Prof. Dr. Footer Person</h2><p>Chair of Footer</p></a></footer>
        """

        result = parse_faculty_page(html, "https://example.edu/department/psychology")

        self.assertEqual(result.fallback_candidates_count, 15)
        self.assertEqual(result.parsed_count, 15)
        self.assertEqual([record.name for record in result.records], [f"Prof. Dr. {name}" for name in names])
        self.assertEqual(len({record.profile_url for record in result.records}), 15)
        self.assertTrue(all(not record.name.startswith("Credit") for record in result.records))

    def test_linked_teaser_fallback_accepts_same_institution_subdomain_profiles(self):
        html = """
        <main class="sidebar-page__main">
          <h2>Meet Our Faculty</h2>
          <section class="faculty-spotlight faculty-spotlight--sidebar">
            <div class="faculty-spotlight__item-link field--item">
              <a href="https://www.example.edu/fac/ada-lovelace">
                <div class="faculty-spotlight__item">
                  <h3 class="faculty-spotlight__item-name">Ada Lovelace</h3>
                  <p class="faculty-spotlight__item-title">Professor, Psychology</p>
                </div>
              </a>
            </div>
            <div class="faculty-spotlight__item-link field--item">
              <a href="https://www.example.edu/fac/grace-hopper">
                <div class="faculty-spotlight__item">
                  <h3 class="faculty-spotlight__item-name">Grace Hopper</h3>
                  <p class="faculty-spotlight__item-title">Associate Professor of Psychology</p>
                </div>
              </a>
            </div>
          </section>
        </main>
        <footer>
          <a href="https://profiles.example.net/fac/external-person">
            <h3>External Person</h3><p>Professor of Psychology</p>
          </a>
        </footer>
        """

        result = parse_faculty_page(html, "https://school.example.edu/psychology/faculty-staff")

        self.assertEqual(result.fallback_candidates_count, 2)
        self.assertEqual(
            [(record.name, record.title, record.profile_url) for record in result.records],
            [
                ("Ada Lovelace", "Professor, Psychology", "https://www.example.edu/fac/ada-lovelace"),
                (
                    "Grace Hopper",
                    "Associate Professor of Psychology",
                    "https://www.example.edu/fac/grace-hopper",
                ),
            ],
        )

    def test_professorship_rows_bind_local_prefixed_name_to_chair_link(self):
        navigation = "".join(
            f'<a href="/institute/{slug}/">{label}</a>'
            for slug, label in (
                ("institute-board", "Institute Board"),
                ("buildings-and-places", "Buildings and Places"),
                ("history", "History of the Institute"),
                ("erasmus", "Erasmus Program"),
            )
        )
        names = [
            "Ada Lovelace",
            "Grace Hopper",
            "Alan Turing",
            "Katherine Johnson",
            "Edsger Dijkstra",
            "Barbara Liskov",
            "Donald Knuth",
            "Margaret Hamilton",
            "Claude Shannon",
            "John McCarthy",
            "Frances Allen",
            "Niklaus Wirth",
        ]
        rows = "".join(
            f"""
            <div class="professorship-row">
              <a href="/chair-{index}/">Research Area {index}</a>
              <p>Prof. Dr. {name} (Chair)</p>
            </div>
            """
            for index, name in enumerate(names, start=1)
        )
        html = f"""
        <main>
          <div class="section-links">{navigation}</div>
          <h1>Professorships</h1>
          <section class="professorship-list">{rows}</section>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/institute/professorships/")

        self.assertEqual(result.candidate_count, 12)
        self.assertEqual(result.parsed_count, 12)
        self.assertEqual([record.name for record in result.records], [f"Prof. Dr. {name}" for name in names])
        self.assertEqual([record.title for record in result.records], [f"Research Area {index}" for index in range(1, 13)])
        self.assertEqual(len({record.profile_url for record in result.records}), 12)
        self.assertFalse({"Institute Board", "Buildings and Places", "History of the Institute", "Erasmus Program"} & {record.name for record in result.records})

    def test_person_card_prefers_person_name_and_rejects_organizational_profile_links(self):
        html = """
        <main><ul class="staff-grid">
          <li class="person-card">
            <h3><a href="/institutes/donders">Behavioural Science</a><span class="person-name">Dr Ada Lovelace</span></h3>
            <p>Professor</p>
            <a href="/faculties/social-sciences">Faculty of Social Sciences</a>
            <a href="/departments/sociology">Sociology Department</a>
            <a href="/research-groups/digital-society">Digital Society Group</a>
            <a href="/people/ada-lovelace">Dr Ada Lovelace</a>
          </li>
        </ul></main>
        """

        result = parse_faculty_page(html, "https://example.edu/staff/")

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].name, "Dr Ada Lovelace")
        self.assertEqual(result.records[0].profile_url, "https://example.edu/people/ada-lovelace")

    def test_existing_single_link_card_profile_extraction_is_unchanged(self):
        html = """
        <main><article class="person-card">
          <h3>Grace Hopper</h3><p>Professor</p>
          <a href="/people/grace-hopper">View profile</a>
        </article></main>
        """

        result = parse_faculty_page(html, "https://example.edu/staff/")

        self.assertEqual(
            [(record.name, record.title, record.profile_url) for record in result.records],
            [("Grace Hopper", "Professor", "https://example.edu/people/grace-hopper")],
        )

    def test_person_card_prefers_same_card_external_bio_link(self):
        html = """
        <main><h2>Full-time Faculty</h2><div class="staff-search-results">
          <article class="person-card">
            <h3>Ada Lovelace</h3><p>Associate Professor</p>
            <a href="/faculty/"><img src="portrait.jpg" alt="Ada Lovelace"></a>
            <a href="/departments/sociology">Sociology Department</a>
            <a href="https://faculty360.example.edu/contact/ada-lovelace">View Ada Lovelace Bio</a>
          </article>
        </div></main>
        """

        result = parse_faculty_page(html, "https://www.example.edu/faculty/")

        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].name, "Ada Lovelace")
        self.assertEqual(result.records[0].profile_url, "https://faculty360.example.edu/contact/ada-lovelace")
        self.assertNotIn("Bio", result.records[0].name)

    def test_person_name_heading_does_not_replace_structural_section_heading(self):
        parser = _FacultyHTMLParser()
        parser.feed(
            """
            <main><h2>Full-time Faculty</h2>
              <h3>Gözde Güran</h3><div class="person-card"><p>Professor</p></div>
              <h3>Ada Lovelace</h3><div class="person-card"><p>Professor</p></div>
            </main>
            """
        )
        cards = [node for node in parser.root.descendants() if "person-card" in node.attr_text("class")]

        self.assertEqual(_nearest_section_heading(cards[1]), "Full-time Faculty")

    def test_rejects_wrapping_profile_anchor_when_it_contains_multiple_people(self):
        html = """
        <main><a href="/employees/directory">
          <div class="result-item"><strong class="fullname">Ada Lovelace</strong><span class="role">Professor</span></div>
          <div class="result-item"><strong class="fullname">Grace Hopper</strong><span class="role">Professor</span></div>
        </a></main>
        """

        result = parse_faculty_page(html, "https://example.edu/sociology/")

        self.assertEqual(result.records, [])
        self.assertEqual(result.ancestor_profile_links_recovered_count, 0)

    def test_splits_flattened_name_title_before_phone_and_email(self):
        links = "".join(
            [
                '<a href="/employees/ada">Ada Lovelace, Professor +47 12345678 ada@example.edu</a>',
                '<a href="/employees/grace">Grace Hopper, Professor, Leader of Computing +47 87654321 grace@example.edu</a>',
            ]
            + [
                f'<a href="/employees/filler-{index}">Filler Person {index}, Programme Coordinator +47 1000000{index}</a>'
                for index in range(8)
            ]
        )
        result = parse_faculty_page(f"<main><h2>Academic Staff</h2><div>{links}</div></main>", "https://example.edu/staff/")

        self.assertEqual(
            [(record.name, record.title) for record in result.records],
            [("Ada Lovelace", "Professor"), ("Grace Hopper", "Professor, Leader of Computing")],
        )
        self.assertEqual(result.flattened_name_title_split_count, 2)
        self.assertTrue(all("+47" not in record.title and "@" not in record.title for record in result.records))

    def test_extracts_bonn_law_businesscard_people(self):
        html = """
        <main>
          <section>
            <div class="tile tile-businesscard">
              <div class="businesscard-content contact-avatar">
                <img class="avatar-circle" alt="Avatar Durner">
              </div>
              <div class="businesscard-content contact-name">
                Prof. Dr. Dr. Wolfgang Durner LL.M.
              </div>
              <div class="businesscard-content contact-email">
                <a href="mailto:lehrstuhl.durner@jura.uni-bonn.de">lehrstuhl.durner@jura.uni-bonn.de</a>
              </div>
              <div class="businesscard-content contact-more">
                <a href="https://www.jura.uni-bonn.de/de/forschung-und-lehre/lehrende-personenverzeichnis/oeffentliches-recht/wolfgang-durner">Additional contact information</a>
              </div>
            </div>
            <div class="tile tile-businesscard">
              <div class="businesscard-content contact-name">Prof. Dr. Klaus Ferdinand Gärditz</div>
              <div class="businesscard-content contact-email">
                <a href="mailto:sekretariat.gaerditz@jura.uni-bonn.de">sekretariat.gaerditz@jura.uni-bonn.de</a>
              </div>
              <div class="businesscard-content contact-more">
                <a href="https://www.jura.uni-bonn.de/de/forschung-und-lehre/lehrende-personenverzeichnis/oeffentliches-recht/klaus-ferdinand-gaerditz">Additional contact information</a>
              </div>
            </div>
            <div class="tile tile-businesscard">
              <div class="businesscard-content contact-name">Prof. Dr. Christian Hillgruber</div>
              <div class="businesscard-content contact-email">
                <a href="mailto:sekretariat.hillgruber@jura.uni-bonn.de">sekretariat.hillgruber@jura.uni-bonn.de</a>
              </div>
              <div class="businesscard-content contact-website">
                <a href="https://www.jura.uni-bonn.de/institut-fuer-kirchenrecht/de">Website</a>
              </div>
            </div>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://www.jura.uni-bonn.de/en/research-and-teaching/teaching-staff")

        self.assertEqual(result.page_type, "card")
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.parsed_count, 2)
        self.assertEqual(
            [record.name for record in result.records],
            ["Prof. Dr. Dr. Wolfgang Durner LL.M.", "Prof. Dr. Klaus Ferdinand Gärditz"],
        )
        self.assertEqual([record.title for record in result.records], ["Professor", "Professor"])
        self.assertEqual(
            result.records[0].profile_url,
            "https://www.jura.uni-bonn.de/de/forschung-und-lehre/lehrende-personenverzeichnis/oeffentliches-recht/wolfgang-durner",
        )
        self.assertTrue(all(record.profile_url for record in result.records))

    def test_extracts_umd_card_name_before_title_and_office(self):
        html = """
        <main>
          <div class="views-row">
            <article typeof="schema:Person" about="/directory/douglas-w-anthony" class="profile">
              <a href="/directory/douglas-w-anthony">
                <div class="field field--name-field-position field__item">Visiting Professor</div>
              </a>
              <div class="field field--name-title">
                <a href="/directory/douglas-w-anthony">Anthony, Douglas W.</a>
              </div>
              <div class="field field--name-field-unit">
                <a href="/about-college/office-dean">Office of the Dean</a>
              </div>
            </article>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://education.umd.edu/academics/departments/tlpl/about/faculty")

        self.assertEqual(result.parsed_count, 1)
        self.assertEqual(result.records[0].name, "Anthony, Douglas W.")
        self.assertNotEqual(result.records[0].name, "Visiting Professor")
        self.assertEqual(result.records[0].title, "Visiting Professor")
        self.assertNotEqual(result.records[0].title, "Office of the Dean")
        self.assertEqual(result.records[0].profile_url, "https://education.umd.edu/directory/douglas-w-anthony")

    def test_recovers_waikato_profile_links_from_staff_cards(self):
        html = """
        <main>
          <div class="staff-profile-block">
            <div class="profile-card">
              <div class="profile-card__content">
                <a href="https://profiles.waikato.ac.nz/leilani.tuala-warren" class="profile-card__title">Judge Leilani Tuala-Warren</a>
                <p class="profile-card__position">Dean Te Piringa Faculty of Law</p>
                <a href="mailto:leilani.tuala-warren@waikato.ac.nz">leilani.tuala-warren@waikato.ac.nz</a>
              </div>
            </div>
            <div class="profile-card">
              <div class="profile-card__content">
                <h3>Dr Alex Smith</h3>
                <p class="profile-card__position">Senior Lecturer</p>
                <a href="mailto:alex.smith@waikato.ac.nz">alex.smith@waikato.ac.nz</a>
                <a href="https://profiles.waikato.ac.nz/search">Search profiles</a>
              </div>
            </div>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://www.waikato.ac.nz/about/faculties-schools/law/staff/")

        self.assertEqual(result.parsed_count, 1)
        self.assertEqual(result.records[0].name, "Judge Leilani Tuala-Warren")
        self.assertEqual(result.records[0].profile_url, "https://profiles.waikato.ac.nz/leilani.tuala-warren")
        self.assertTrue(all(record.profile_url for record in result.records))
        self.assertEqual(result.cards_missing_profile_url_count, 2)
        self.assertEqual(result.card_recovered_profile_links_count, 1)

    def test_card_name_ignores_generic_profile_detail_link_text(self):
        html = """
        <main>
          <div class="faculty-card">
            <div class="title">Dr Eyup Guler</div>
            <p>Associate Professor</p>
            <a href="mailto:eyiguler@itu.edu.tr">eyiguler@itu.edu.tr</a>
            <a href="https://akademi.itu.edu.tr/eyiguler">Profile Detail</a>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://uubf.itu.edu.tr/en/staff/academic-staff")

        self.assertEqual(result.parsed_count, 1)
        self.assertEqual(result.records[0].name, "Dr Eyup Guler")
        self.assertNotEqual(result.records[0].name, "Profile Detail")
        self.assertEqual(result.records[0].profile_url, "https://akademi.itu.edu.tr/eyiguler")
        self.assertEqual(result.card_recovered_profile_links_count, 1)
        self.assertEqual(
            result.card_profile_link_debug[0],
            {
                "extracted_name": "Dr Eyup Guler",
                "recovered_url": "https://akademi.itu.edu.tr/eyiguler",
                "link_text": "Profile Detail",
                "drop_reason": "ok",
                "profile_search_scope": "inside_card",
                "scanned_sibling_count": 0,
                "stop_boundary": "",
                "reject_reason": "",
            },
        )

    def test_recovers_itu_rehber_cards_with_embedded_akademi_profile_links(self):
        html = """
        <main>
          <section class="personel-container">
            <div class="personel-card">
              <div class="person-name">Dr Eyup Guler</div>
              <div class="person-title">Associate Professor</div>
              <a href="https://rehber.itu.edu.tr/search?q=eyiguler">Contact</a>
              <a href="#" data-url="https://akademi.itu.edu.tr/eyiguler">Profile Detail</a>
            </div>
            <div class="personel-card">
              <div class="person-name">Dr Murat Saritas</div>
              <div class="person-title">Professor</div>
              <a href="https://rehber.itu.edu.tr/search?q=muratsaritas">Contact</a>
              <button onclick="location.href='https://akademi.itu.edu.tr/muratsaritas'">Profile Detail</button>
            </div>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://uubf.itu.edu.tr/en/staff/academic-staff")

        self.assertEqual(result.parsed_count, 2)
        self.assertEqual([record.name for record in result.records], ["Dr Eyup Guler", "Dr Murat Saritas"])
        self.assertNotIn("Profile Detail", [record.name for record in result.records])
        self.assertEqual(
            [record.profile_url for record in result.records],
            ["https://akademi.itu.edu.tr/eyiguler", "https://akademi.itu.edu.tr/muratsaritas"],
        )

    def test_extracts_bu_anchor_wrapped_profile_listing_items(self):
        html = """
        <html>
          <body class="page sidebar-location-right">
            <main>
              <article class="content-area">
                <ul class="profile-listing profile-format-mini">
                  <a href="https://www.bu.edu/pardeeschool/profile/thomas-berger/">
                    <li class="profile-item profile-item-mini profile type-profile">
                      <h6 class="profile-name profile-name-mini">Thomas Berger</h6>
                      <p class="pardee-mini-title">Professor of International Relations</p>
                    </li>
                  </a>
                  <a href="https://www.bu.edu/pardeeschool/profile/rachel-brule/">
                    <li class="profile-item profile-item-mini profile type-profile">
                      <h6 class="profile-name profile-name-mini">Rachel Brule</h6>
                      <p class="pardee-mini-title">Associate Professor of Global Development Policy</p>
                    </li>
                  </a>
                  <a href="https://www.bu.edu/pardeeschool/profile/alexander-de-la-paz/">
                    <li class="profile-item profile-item-mini profile type-profile">
                      <h6 class="profile-name profile-name-mini">Alexander de la Paz</h6>
                      <p class="pardee-mini-title">Assistant Professor of International Security</p>
                    </li>
                  </a>
                </ul>
              </article>
            </main>
          </body>
        </html>
        """

        result = parse_faculty_page(html, "https://www.bu.edu/pardeeschool/academics/core-faculty/")

        self.assertEqual(result.possible_person_link_count, 3)
        self.assertEqual(result.candidate_count, 3)
        self.assertEqual(result.parsed_count, 3)
        self.assertEqual([record.name for record in result.records], ["Thomas Berger", "Rachel Brule", "Alexander de la Paz"])
        self.assertEqual(
            [record.title for record in result.records],
            [
                "Professor of International Relations",
                "Associate Professor of Global Development Policy",
                "Assistant Professor of International Security",
            ],
        )
        self.assertEqual(result.records[0].profile_url, "https://www.bu.edu/pardeeschool/profile/thomas-berger/")

    def test_extracts_fu_berlin_professorship_paragraph_links(self):
        html = """
        <main>
          <div class="editor-content hyphens">
            <p><strong>Private Law</strong></p>
            <blockquote>
              <p><a href="https://www.jura.fu-berlin.de/fachbereich/einrichtungen/zivilrecht/lehrende/engerta/index.html">Univ.-Prof. Dr. Andreas Engert, LL.M. (Chicago)</a> (Private Law, European Company Law)</p>
              <p><a href="/fachbereich/einrichtungen/zivilrecht/lehrende/hartmannf/index.html">Univ.-Prof. Dr. Felix Hartmann, LL.M. (Harvard)</a> (Private Law, Labor Law)</p>
            </blockquote>
            <p><strong>Public Law</strong></p>
            <blockquote>
              <p><a href="/fachbereich/einrichtungen/oeffentliches-recht/lehrende/kriegerh/index.html">Univ.-Prof. Dr. Heike Krieger</a> (Human Rights, Public International Law)</p>
            </blockquote>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://www.jura.fu-berlin.de/en/forschung/professuren/index.html")

        self.assertEqual(result.possible_person_link_count, 3)
        self.assertEqual(result.candidate_count, 3)
        self.assertEqual(result.parsed_count, 3)
        self.assertEqual(
            [record.name for record in result.records],
            [
                "Univ.-Prof. Dr. Andreas Engert, LL.M. (Chicago)",
                "Univ.-Prof. Dr. Felix Hartmann, LL.M. (Harvard)",
                "Univ.-Prof. Dr. Heike Krieger",
            ],
        )
        self.assertEqual(
            [record.title for record in result.records],
            ["Private Law, European Company Law", "Private Law, Labor Law", "Human Rights, Public International Law"],
        )
        self.assertEqual(
            result.records[1].profile_url,
            "https://www.jura.fu-berlin.de/fachbereich/einrichtungen/zivilrecht/lehrende/hartmannf/index.html",
        )

    def test_extracts_generic_title_table_name_links(self):
        html = """
        <main>
          <h2>Faculty Members</h2>
          <table>
            <tbody>
              <tr>
                <td><a href="https://rd.example.edu/en/abc123.html">EL Balti Béligh</a></td>
                <td>Professor</td>
                <td>Private International Law</td>
              </tr>
              <tr>
                <td><a href="https://rd.example.edu/en/def456.html">FUKUDA Masaki</a></td>
                <td>Associate Professor</td>
                <td>Information and Communications Law</td>
              </tr>
            </tbody>
          </table>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/about.html")

        self.assertEqual(result.possible_person_link_count, 2)
        self.assertEqual(result.page_type, "table")
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.parsed_count, 2)
        self.assertEqual([record.name for record in result.records], ["EL Balti Béligh", "FUKUDA Masaki"])
        self.assertEqual([record.title for record in result.records], ["Professor", "Associate Professor"])
        self.assertEqual(result.records[0].profile_url, "https://rd.example.edu/en/abc123.html")

    def test_unknown_page_uses_repeated_person_link_fallback_candidates(self):
        html = """
        <main>
          <section class="unav-people-list">
            <div class="unav-people-list__people-container">
              <div class="unav-people-list__people-item">
                <img alt="Maria Aparisi" src="/maria.jpg"></img>
                <p class="unav-people-list__name">Maria Aparisi</p>
                <p class="unav-people-list__job">Full Professor</p>
                <a class="unav-people__arrow-link" href="/web/investigacion/nuestros-investigadores/detalle-investigadores-cv?investigadorId=100376">View CV</a>
              </div>
              <div class="unav-people-list__people-item">
                <img alt="Luis Arrieta" src="/luis.jpg"></img>
                <p class="unav-people-list__name">Luis Arrieta</p>
                <p class="unav-people-list__job">Associate Professor</p>
                <a class="unav-people__arrow-link" href="/web/investigacion/nuestros-investigadores/detalle-investigadores-cv?investigadorId=106142">View CV</a>
              </div>
              <div class="unav-people-list__people-item">
                <img alt="No Title" src="/missing.jpg"></img>
                <p class="unav-people-list__name">No Title</p>
                <a class="unav-people__arrow-link" href="/web/investigacion/nuestros-investigadores/detalle-investigadores-cv?investigadorId=111111">View CV</a>
              </div>
            </div>
          </section>
          <nav><a href="javascript:void(0)">Programs</a></nav>
        </main>
        """

        result = parse_faculty_page(
            html,
            "https://en.unav.edu/web/school-of-law/about-the-school/who-are-we/academic-staff",
        )

        self.assertEqual(result.page_type, "unknown")
        self.assertEqual(result.candidate_count, 3)
        self.assertEqual(result.fallback_person_links_count, 3)
        self.assertEqual(result.fallback_candidates_count, 3)
        self.assertEqual([record.name for record in result.records], ["Maria Aparisi", "Luis Arrieta"])
        self.assertEqual([record.title for record in result.records], ["Full Professor", "Associate Professor"])
        self.assertEqual(
            result.records[0].profile_url,
            "https://en.unav.edu/web/investigacion/nuestros-investigadores/detalle-investigadores-cv?investigadorId=100376",
        )
        self.assertEqual(result.fallback_link_debug[0]["inferred_title"], "Full Professor")
        self.assertEqual(result.fallback_link_debug[2]["drop_reason"], "missing_title")

    def test_unknown_page_recovers_profile_urls_from_person_headings(self):
        html = """
        <main>
          <h1>Academic Staff</h1>
          <section class="experts">
            <div data-href="/en/experts/igor-adamczyk">
              <h2>Igor Adamczyk</h2>
              <p>Assistant Professor</p>
            </div>
            <div onclick="window.location='/en/experts/dobrochna-bach-golecka'">
              <h2>Dobrochna Bach-Golecka</h2>
              <p>Associate Professor</p>
            </div>
            <div>
              <h2>Michal Baldowski</h2>
              <p>Lecturer</p>
              <a href="/en/experts/michal-baldowski">Profile</a>
            </div>
            <a href="/en/experts/anna-nowak">
              <span>Open profile</span>
            </a>
            <div>
              <h2>Anna Nowak</h2>
              <p>Professor</p>
            </div>
            <div data-href="/en/experts/no-title">
              <h2>No Title</h2>
            </div>
          </section>
          <nav>
            <h2>Navigation Person</h2>
            <a href="/en/experts/navigation-person">Profile</a>
          </nav>
        </main>
        """

        result = parse_faculty_page(html, "https://wpia.uw.edu.pl/en/eksperci")

        self.assertEqual(result.page_type, "unknown")
        self.assertEqual(result.heading_person_candidates_count, 5)
        self.assertEqual(result.recovered_profile_links_count, 5)
        self.assertEqual(result.candidate_count, 5)
        self.assertEqual(
            [record.name for record in result.records],
            ["Igor Adamczyk", "Dobrochna Bach-Golecka", "Michal Baldowski", "Anna Nowak"],
        )
        self.assertEqual(
            [record.profile_url for record in result.records],
            [
                "https://wpia.uw.edu.pl/en/experts/igor-adamczyk",
                "https://wpia.uw.edu.pl/en/experts/dobrochna-bach-golecka",
                "https://wpia.uw.edu.pl/en/experts/michal-baldowski",
                "https://wpia.uw.edu.pl/en/experts/anna-nowak",
            ],
        )
        self.assertEqual(result.heading_person_link_debug[0]["recovered_url"], "/en/experts/igor-adamczyk")
        self.assertEqual(result.heading_person_link_debug[4]["drop_reason"], "missing_title")

    def test_flags_iit_dynamic_filtered_faculty_table_low_coverage(self):
        html = """
        <main>
          <form method="POST" action="#">
            <select id="department" name="department">
              <option value="">Select Department</option>
              <option value="AE">Aerospace Engineering</option>
            </select>
          </form>
          <table id="faclist">
            <thead>
              <tr>
                <th>Faculty</th>
                <th>Department</th>
                <th>Designation</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><a href="/department/AE/faculty/ae-john-doe">John Doe</a></td>
                <td>Aerospace Engineering</td>
                <td>Professor</td>
              </tr>
              <tr>
                <td><a href="/department/AE/faculty/ae-jane-smith">Jane Smith</a></td>
                <td>Aerospace Engineering</td>
                <td>Associate Professor</td>
              </tr>
            </tbody>
          </table>
          <script>
            $('#faclist').DataTable({
              ajax: { url: 'https://www.iitkgp.ac.in/Departments/fetchAllFacListByDept' }
            });
          </script>
        </main>
        """

        result = parse_faculty_page(html, "https://www.iitkgp.ac.in/faclistbydepartment")

        self.assertEqual(result.page_type, "table")
        self.assertEqual(result.parsed_count, 2)
        self.assertEqual([record.name for record in result.records], ["John Doe", "Jane Smith"])
        self.assertTrue(any("possible_dynamic_or_filtered_directory" in item for item in result.href_patterns_debug))
        self.assertTrue(any("department_select=True" in item for item in result.href_patterns_debug))
        self.assertTrue(any("form_action=#" in item for item in result.href_patterns_debug))
        self.assertTrue(any("fetchAllFacListByDept" in item for item in result.href_patterns_debug))

    def test_locale_scoped_short_profile_cards_are_detected_and_deduplicated_by_url(self):
        html = """
        <main>
          <section class="staff-directory">
            <div class="person-entry">
              <a href="/pt/p/1001"><img src="/ana.jpg" alt="Portrait"></a>
              <h3><a href="/pt/p/1001">Ana Silva</a></h3>
              <p>Associate Professor</p>
            </div>
            <div class="person-entry">
              <a href="/en-GB/p/A1002"><img src="/bruno.jpg" alt="Portrait"></a>
              <h3><a href="/en-GB/p/A1002">Bruno Costa</a></h3>
              <p>Assistant Professor</p>
            </div>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/pt/department/psychology")

        self.assertEqual(result.possible_person_link_count, 2)
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.parsed_count, 2)
        self.assertEqual([record.name for record in result.records], ["Ana Silva", "Bruno Costa"])
        self.assertEqual(
            [record.profile_url for record in result.records],
            [
                "https://example.edu/pt/p/1001",
                "https://example.edu/en-GB/p/A1002",
            ],
        )

    def test_locale_scoped_short_profile_link_creates_a_local_person_candidate(self):
        html = """
        <main>
          <div class="directory-entry">
            <h3>Carla Santos</h3>
            <p>Professor</p>
            <a href="/pt/p/opaque_1003">More details</a>
          </div>
          <div class="directory-entry">
            <h3>Daniel Sousa</h3>
            <p>Associate Professor</p>
            <a href="/pt/p/opaque_1004">More details</a>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/pt/department/psychology")

        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.parsed_count, 2)
        self.assertEqual([record.name for record in result.records], ["Carla Santos", "Daniel Sousa"])
        self.assertEqual(result.records[0].profile_url, "https://example.edu/pt/p/opaque_1003")

    def test_profile_recovery_stops_at_next_person_and_rejects_policy_links(self):
        html = """
        <main>
          <div class="profile-card">
            <p class="name">Ana Silva</p>
            <p>Associate Professor</p>
            <p>ana.silva@example.edu</p>
          </div>
          <div class="profile-card">
            <p class="name"><a href="/pt/p/B1002">Bruno Costa</a></p>
            <p>Professor</p>
          </div>
          <div class="external-profile">
            <a href="https://researchprofiles.other.edu/person/bruno-costa">External profile</a>
          </div>
          <div class="quick-links cookie-preferences">
            <a class="name" href="/pt/privacy-policy">Privacy Options</a>
            <p>Professor</p>
            <a href="/pt/cookie-policy">Cookie Preferences</a>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/pt/department/psychology")

        self.assertEqual([record.name for record in result.records], ["Bruno Costa"])
        self.assertEqual(result.records[0].profile_url, "https://example.edu/pt/p/B1002")
        self.assertEqual(result.possible_person_link_count, 1)
        self.assertTrue(
            any(item.get("stop_boundary") == "next_person_profile_link" for item in result.card_profile_link_debug)
        )

    def test_segments_group_titled_locale_profile_cards_without_scanning_utility_content(self):
        names = [
            "Ana Silva",
            "Bruno Costa",
            "Carla Santos",
            "Daniel Sousa",
            "Eva Martins",
            "Fabio Rocha",
            "Gabriela Pinto",
            "Hugo Ribeiro",
            "Ines Correia",
            "Joao Ferreira",
        ]
        groups = []
        for group_index, title in enumerate(("Associate Professor", "Assistant Professor")):
            cards = []
            for index, name in enumerate(names[group_index * 5 : (group_index + 1) * 5], start=group_index * 5 + 1):
                cards.append(
                    f"""
                    <div class="grid-column">
                      <div class="directory-person">
                        <a href="/pt/p/U{index:04d}"><img src="/{index}.jpg" alt="Portrait"></a>
                        <a href="/pt/p/U{index:04d}">{name}</a>
                        <a href="mailto:person{index}@example.edu">person{index}@example.edu</a>
                      </div>
                    </div>
                    """
                )
            groups.append(
                f"""
                <div class="people-group">
                  <div class="group-label"><p>{title}</p></div>
                  <div class="people-grid">{''.join(cards)}</div>
                </div>
                """
            )
        html = f"""
        <html>
          <body>
            <section class="directory-shell">{''.join(groups)}</section>
            <footer>
              <div class="row justify-content-between">
                <a href="/pt/privacy-policy">Privacy Options</a>
              </div>
            </footer>
            <div id="onetrust-consent-sdk">
              <a href="/pt/cookie-policy">Cookie Preferences</a>
            </div>
          </body>
        </html>
        """

        result = parse_faculty_page(html, "https://example.edu/pt/department/psychology")

        self.assertEqual(result.possible_person_link_count, 10)
        self.assertEqual(result.wrapper_person_links_count, 10)
        self.assertEqual(result.segmented_person_blocks_count, 10)
        self.assertEqual(result.candidate_count, 10)
        self.assertEqual(result.parsed_count, 10)
        self.assertEqual([record.name for record in result.records], names)
        self.assertEqual(
            [record.title for record in result.records],
            ["Associate Professor"] * 5 + ["Assistant Professor"] * 5,
        )
        self.assertEqual(len({record.profile_url for record in result.records}), 10)
        self.assertEqual(result.records[0].profile_url, "https://example.edu/pt/p/U0001")
        self.assertEqual(result.records[0].email, "person1@example.edu")
        self.assertNotIn("Privacy Options", [record.name for record in result.records])
        self.assertNotIn("Cookie Preferences", [record.name for record in result.records])

    def test_people_role_filters_do_not_supply_a_director_title(self):
        html = """
        <main>
          <div class="person-card department-contact">
            <div class="responsabile">
              <strong>Director</strong>
              <a href="/people/dana-director">Dana Director</a>
            </div>
            <div class="role-filter-controls">
              <a href="" ng-click="directory.setRoleFilter('professor')">Full professor</a>
              <label ng-model="directory.items" ng-change="directory.changePageSize()">48</label>
            </div>
            <div class="people-results">
              <div class="person-result">
                <h4><a href="/people/ada-lovelace">Ada Lovelace</a></h4>
                <span>Associate professor</span>
                <a href="mailto:ada@example.edu">ada@example.edu</a>
              </div>
            </div>
          </div>
        </main>
        """

        parser = _FacultyHTMLParser()
        parser.feed(html)
        director_block = next(
            node
            for node in parser.root.descendants()
            if "person-card" in node.attr_text("class").split()
        )

        result = parse_faculty_page(html, "https://example.edu/department/people")

        self.assertEqual(_extract_title(director_block, "Dana Director"), "")
        self.assertEqual(
            [(record.name, record.title) for record in result.records],
            [("Ada Lovelace", "Associate professor")],
        )
        self.assertFalse(
            any(
                item.get("name") == "Dana Director" and item.get("title") == "Full professor"
                for item in result.dropped_candidate_debug
            )
        )

    def test_dynamic_people_result_items_keep_fields_local_and_missing_titles_rejected(self):
        html = """
        <main>
          <div class="people-results">
            <div class="person-result">
              <h4><a href="/people/ada-lovelace">Ada Lovelace</a></h4>
              <span>Full professor</span>
              <a href="mailto:ada@example.edu">ada@example.edu</a>
            </div>
            <div class="person-result">
              <h4><a href="/people/grace-hopper">Grace Hopper</a></h4>
              <a href="mailto:grace@example.edu">grace@example.edu</a>
            </div>
            <div class="role-filter-controls">
              <button type="button">Associate professor</button>
            </div>
            <div class="person-result">
              <h4><a href="/people/alan-turing">Alan Turing</a></h4>
              <span>Teaching assistant</span>
              <a href="mailto:alan@example.edu">alan@example.edu</a>
            </div>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/department/people")

        self.assertEqual(
            [(record.name, record.title, record.profile_url, record.email) for record in result.records],
            [
                (
                    "Ada Lovelace",
                    "Full professor",
                    "https://example.edu/people/ada-lovelace",
                    "ada@example.edu",
                )
            ],
        )
        self.assertNotIn("Grace Hopper", [record.name for record in result.records])
        self.assertNotIn("Alan Turing", [record.name for record in result.records])

    def test_bounded_accordion_people_use_person_h2_role_group_and_local_website(self):
        html = """
        <main>
          <h3>Core professorships</h3>
          <div class="accordion people-list">
            <section>
              <h2>Prof. Dr. Ada Lovelace</h2>
              <p>Decision Sciences</p>
              <div class="details">
                <h3>Contact</h3>
                <a href="https://profiles.example.edu/people/ada-lovelace">Website</a>
                <a href="mailto:ada@example.edu">Write an e-mail</a>
                <h3>Office Hours</h3>
                <p>By appointment</p>
                <h3>Responsibilities</h3>
                <a href="https://publications.example.net/ada">To the publication list</a>
              </div>
            </section>
            <section>
              <h2>Prof. Dr. Grace Hopper</h2>
              <div class="details">
                <h3>Contact</h3>
                <a href="mailto:grace@example.edu">Write an e-mail</a>
                <a href="https://publications.example.net/grace">To the publication list</a>
              </div>
            </section>
            <section>
              <h2>Prof. Dr. Alan Turing</h2>
              <div class="details">
                <h3>Contact</h3>
                <a href="https://profiles.example.edu/people/alan-turing">Website</a>
                <a href="mailto:alan@example.edu">Write an e-mail</a>
                <a href="https://unrelated.example.net/research/alan">Details</a>
              </div>
            </section>
          </div>
        </main>
        """

        result = parse_faculty_page(html, "https://psychology.example.edu/department/professors/")

        self.assertEqual(
            [(record.name, record.title, record.profile_url, record.email) for record in result.records],
            [
                (
                    "Prof. Dr. Ada Lovelace",
                    "Core professorships",
                    "https://profiles.example.edu/people/ada-lovelace",
                    "ada@example.edu",
                ),
                (
                    "Prof. Dr. Alan Turing",
                    "Core professorships",
                    "https://profiles.example.edu/people/alan-turing",
                    "alan@example.edu",
                ),
            ],
        )
        self.assertNotIn("Prof. Dr. Grace Hopper", [record.name for record in result.records])
        self.assertTrue(all("publication" not in record.profile_url for record in result.records))
        self.assertFalse(
            {"Contact", "Office Hours", "Responsibilities"} & set(result.section_headings_debug)
        )

        parser = _FacultyHTMLParser()
        parser.feed(html)
        details = next(
            node
            for node in parser.root.descendants()
            if "details" in node.attr_text("class").split()
        )
        ada_website = next(
            link
            for link in parser.links
            if link.text() == "Website" and "ada-lovelace" in link.attr_text("href")
        )
        self.assertEqual(_extract_name(details), "")
        self.assertEqual(_nearest_section_heading(ada_website), "Core professorships")

    def test_accordion_role_groups_keep_supported_people_and_exclude_emeritus(self):
        html = """
        <main>
          <h3>Extraordinary Professors</h3>
          <section>
            <h2>apl. Prof. Dr. Katherine Johnson</h2>
            <h3>Contact</h3>
            <a href="https://profiles.example.edu/people/katherine-johnson">Website</a>
          </section>
          <h3>Emeritus Professors</h3>
          <section>
            <h2>Prof. Dr. John von Neumann</h2>
            <h3>Responsibilities</h3>
            <a href="https://profiles.example.edu/people/john-von-neumann">Website</a>
          </section>
          <h3>Coopted Professors</h3>
          <section>
            <h2>Norbert Wiener</h2>
            <h3>Contact</h3>
            <a href="https://profiles.example.edu/people/norbert-wiener">Website</a>
          </section>
          <h3>Privatdozent (PD)</h3>
          <section>
            <h2>PD Claude Shannon Ph.D.</h2>
            <h3>Details</h3>
            <a href="https://profiles.example.edu/people/claude-shannon">Website</a>
          </section>
        </main>
        """

        result = parse_faculty_page(html, "https://psychology.example.edu/department/professors/")

        self.assertEqual(
            [(record.name, record.title) for record in result.records],
            [
                ("apl. Prof. Dr. Katherine Johnson", "Extraordinary Professors"),
                ("Norbert Wiener", "Coopted Professors"),
                ("PD Claude Shannon Ph.D.", "Privatdozent (PD)"),
            ],
        )
        self.assertNotIn("Prof. Dr. John von Neumann", [record.name for record in result.records])
        self.assertNotIn("Contact", [record.name for record in result.records])
        self.assertNotIn("Responsibilities", [record.name for record in result.records])

    def test_title_pending_requires_reliable_person_evidence_in_explicit_academic_section(self):
        html = """
        <main>
          <h2>Academic Staff</h2>
          <article class="person-card">
            <h3><a href="/people/ada-lovelace">Ada Lovelace</a></h3>
            <p class="title">Dr.</p>
            <a href="mailto:ada@example.edu">ada@example.edu</a>
          </article>
          <article class="person-card">
            <h3><a href="/people/grace-hopper">Grace Hopper</a></h3>
          </article>
          <article class="person-card">
            <h3><a href="/people/alan-turing">Alan Turing</a></h3>
            <p class="title">Lecturer</p>
          </article>
          <article class="person-card">
            <h3><a href="/people/katherine-johnson">Katherine Johnson</a></h3>
            <p class="title">Professor</p>
          </article>
          <article class="person-card">
            <h3>No Profile Person</h3>
            <p class="title">Dr</p>
          </article>
          <article class="person-card">
            <h3><a href="/people/student-person">Student Person</a></h3>
            <p class="title">PhD Student</p>
          </article>
          <article class="person-card">
            <h3><a href="/people/program-coordinator">Casey Coordinator</a></h3>
            <p>Program Coordinator</p>
          </article>
          <article class="person-card">
            <h3><a href="/people/teaching-assistant">Taylor Assistant</a></h3>
            <p>Teaching Assistant</p>
          </article>

          <h2>Administrative Staff</h2>
          <article class="person-card">
            <h3><a href="/people/admin-person">Admin Person</a></h3>
            <p class="title">Dr.</p>
          </article>

          <h2>Emeritus Faculty</h2>
          <article class="person-card">
            <h3><a href="/people/retired-person">Retired Person</a></h3>
          </article>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/directory")

        self.assertEqual(
            [(record.name, record.title) for record in result.records],
            [("Alan Turing", "Lecturer"), ("Katherine Johnson", "Professor")],
        )
        self.assertEqual(
            [
                (
                    record.name,
                    record.directory_title,
                    record.profile_url,
                    record.email,
                    record.section,
                    record.source_url,
                    record.pending_reason,
                    record.next_action,
                    record.status,
                )
                for record in result.title_pending_records
            ],
            [
                (
                    "Ada Lovelace",
                    "Dr.",
                    "https://example.edu/people/ada-lovelace",
                    "ada@example.edu",
                    "Academic Staff",
                    "https://example.edu/directory",
                    "honorific_only_title",
                    "extract_title_from_profile",
                    "pending",
                ),
                (
                    "Grace Hopper",
                    "",
                    "https://example.edu/people/grace-hopper",
                    "",
                    "Academic Staff",
                    "https://example.edu/directory",
                    "missing_title",
                    "extract_title_from_profile",
                    "pending",
                ),
            ],
        )

    def test_unknown_page_recovers_repeated_opaque_name_links_from_full_time_faculty_section(self):
        names = [
            "Ada Lovelace",
            "Grace Hopper",
            "Katherine Johnson",
            "Alan Turing",
            "Emmy Noether",
            "Claude Shannon",
            "Barbara Liskov",
            "Donald Knuth",
            "Edsger Dijkstra",
            "Frances Allen",
            "John McCarthy",
            "Margaret Hamilton",
            "Niklaus Wirth",
            "Radia Perlman",
            "Tim Berners-Lee",
            "Anita Borg",
            "Mary Jackson",
        ]
        titles = [
            "Professor",
            "Associate Professor",
            "Assistant Professor",
            "Associate Professor",
            "Professor",
            "Lecturer",
            "Assistant Professor",
            "Assistant Professor",
            "Associate Professor",
            "Instructor",
            "Assistant Professor",
            "Instructor",
            "Visiting Assoc. Prof.",
            "Assistant Professor",
            "Lecturer",
            "Professor",
            "Associate Professor",
        ]
        faculty_cards = []
        for index, (name, title) in enumerate(zip(names, titles, strict=True), start=1):
            name_tag = "h4" if index == 1 else "p"
            faculty_cards.append(
                f"""
                <figure><img src="/faculty-{index}.jpg" alt=""></figure>
                <{name_tag} class="has-large-font-size">
                  <a href="/?page_id={7000 + index}" data-type="page">{name}</a>
                </{name_tag}>
                <h5>{title}</h5>
                <h5><strong>Office:</strong> H-{index}</h5>
                <h5><strong>Phone:</strong> +90 312 290 {index:04d}</h5>
                <h5>E-mail: <a href="mailto:faculty{index}@example.edu">faculty{index}@example.edu</a></h5>
                <h5><strong>Lab Page:</strong> Example Research Lab</h5>
                <p>.</p>
                """
            )
        html = f"""
        <header><a href="/?page_id=9001">Header Person</a></header>
        <nav><a href="/?page_id=9002">Navigation Person</a></nav>
        <main>
          <div class="entry-content">
            <div class="heading-group">
              <h3><strong>Full-time Faculty</strong></h3>
              <hr>
            </div>
            {''.join(faculty_cards)}
            <p><a href="/?page_id=7001">Ada Lovelace</a></p>
            <h5>Professor</h5>
            <p><a href="/?page_id=6084">Current Page Person</a></p>
            <h5>Professor</h5>
          </div>
          <h2>Research Areas</h2>
          <section><a href="/?page_id=9100">Clinical Psychology</a></section>
        </main>
        <footer><a href="/?page_id=9003">Footer Person</a></footer>
        """

        result = parse_faculty_page(html, "https://example.edu/?page_id=6084")

        self.assertEqual(result.page_type, "unknown")
        self.assertEqual(result.candidate_count, 17)
        self.assertEqual(result.fallback_person_links_count, 17)
        self.assertEqual(result.fallback_candidates_count, 17)
        self.assertEqual(result.parsed_count, 17)
        self.assertEqual([record.name for record in result.records], names)
        self.assertEqual([record.title for record in result.records], titles)
        self.assertEqual(
            [record.email for record in result.records],
            [f"faculty{index}@example.edu" for index in range(1, 18)],
        )
        self.assertEqual(len({record.profile_url for record in result.records}), 17)
        self.assertEqual(result.records[0].profile_url, "https://example.edu/?page_id=7001")
        self.assertNotIn("Navigation Person", [record.name for record in result.records])
        self.assertNotIn("Clinical Psychology", [record.name for record in result.records])
        self.assertNotIn("Footer Person", [record.name for record in result.records])
        self.assertNotIn("Current Page Person", [record.name for record in result.records])

    def test_recovers_filtered_staff_from_embedded_profile_data(self):
        html = """
        <main>
          <h1>People</h1>
          <div id="profile-search" x-data="profilesearch">
            <template x-for="profile in filteredProfiles"></template>
          </div>
        </main>
        <script>
          window.UNIVERSITY = window.UNIVERSITY || {};
          window.UNIVERSITY.staff_profiles = [
            {
              "username": "ada", "title": "Professor", "first_name": "Ada",
              "last_name": "Lovelace", "roles_flattened": "Professor of Psychology",
              "roles": [{"role": "Professor of Psychology"}],
              "email": "ada@example.edu", "id": 101
            },
            {
              "username": "grace", "title": "Dr", "first_name": "Grace",
              "last_name": "Hopper", "roles_flattened": "Reader in Psychology",
              "roles": [{"role": "Reader in Psychology"}],
              "email": "grace@example.edu", "id": 102
            },
            {
              "username": "admin", "title": "Ms", "first_name": "Office",
              "last_name": "Manager", "roles_flattened": "School Administrator",
              "roles": [{"role": "School Administrator"}],
              "email": "admin@example.edu", "id": 103
            }
          ];
          window.UNIVERSITY.staff_profiles_base_url = "https://example.edu/school/people";
          window.UNIVERSITY.manual_tabs = [
            {"title": "Academic staff", "usernames": "ada, grace"},
            {"title": "Professional services", "usernames": "admin"}
          ];
        </script>
        """

        result = parse_faculty_page(
            html,
            "https://example.edu/school/people?staff=Academic+staff",
        )

        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.parsed_count, 2)
        self.assertEqual(
            [(record.name, record.title, record.profile_url, record.email) for record in result.records],
            [
                (
                    "Professor Ada Lovelace",
                    "Professor of Psychology",
                    "https://example.edu/school/people/101/lovelace-ada",
                    "ada@example.edu",
                ),
                (
                    "Dr Grace Hopper",
                    "Reader in Psychology",
                    "https://example.edu/school/people/102/hopper-grace",
                    "grace@example.edu",
                ),
            ],
        )

    def test_title_pending_rejects_uncertain_or_nonacademic_sections(self):
        html = """
        <main>
          <h2>Faculty and Staff</h2>
          <article class="person-card">
            <h3><a href="/people/neutral-person">Neutral Person</a></h3>
            <p class="title">Dr.</p>
          </article>
          <h2>People</h2>
          <article class="person-card">
            <h3><a href="/people/unknown-person">Unknown Person</a></h3>
          </article>
          <h2>Academic Staff</h2>
          <article class="person-card">
            <h3><a href="/departments/psychology">Department Profile</a></h3>
            <p class="title">Dr.</p>
          </article>
        </main>
        """

        result = parse_faculty_page(html, "https://example.edu/directory")

        self.assertEqual(result.title_pending_records, [])


if __name__ == "__main__":
    unittest.main()
